// Variante mejorada y separada. No sustituye deform_inbreast.cpp.
// Compilar EXE:
//   g++ -std=c++17 -O3 -static -o deform_inbreast_mejorado.exe deform_inbreast_mejorado.cpp
// Compilar DLL:
//   g++ -std=c++17 -O3 -shared -static -DINBREAST_MEJORADO_LIBRARY -o deform_inbreast_mejorado.dll deform_inbreast_mejorado.cpp

#define INBREAST_LIBRARY
#include "deform_inbreast.cpp"

struct ImprovedResult {
    double threshold{};
    size_t candidates{};
    size_t tp{};
    size_t fp{};
    bool detected{};
};

static float percentile(std::vector<float> values, double q) {
    if (values.empty()) return 0.0f;
    const size_t index = static_cast<size_t>(std::clamp(q, 0.0, 1.0) * (values.size() - 1));
    std::nth_element(values.begin(), values.begin() + index, values.end());
    return values[index];
}

// Los DICOM de INbreast no incluyen WindowCenter/WindowWidth. El preprocesador
// anterior transforma el fondo 0 en 0.5. Esta etapa recupera fondo cero y
// normaliza el tejido con percentiles robustos dentro de la mama.
static std::vector<float> robust_renormalize(const std::vector<float>& image,
                                             const std::vector<uint8_t>& mask) {
    std::vector<float> tissue;
    tissue.reserve(image.size() / 2);
    for (size_t p = 0; p < image.size(); ++p) {
        if (mask[p]) tissue.push_back(image[p]);
    }
    const float lo = percentile(tissue, 0.005);
    const float hi = percentile(std::move(tissue), 0.995);
    const float scale = std::max(hi - lo, 1e-6f);
    std::vector<float> result(image.size(), 0.0f);
    for (size_t p = 0; p < image.size(); ++p) {
        if (!mask[p]) continue;
        result[p] = std::clamp((image[p] - lo) / scale, 0.0f, 1.0f);
    }
    return result;
}

// Erosion cuadrada mediante imagen integral. El margen de 15 px reduce
// respuestas producidas por el borde de la piel sin un coste O(radio^2).
static std::vector<uint8_t> erode_mask_box(const std::vector<uint8_t>& mask,
                                           uint32_t rows, uint32_t cols,
                                           int radius) {
    const size_t stride = static_cast<size_t>(cols) + 1;
    std::vector<uint32_t> integral((static_cast<size_t>(rows) + 1) * stride, 0);
    for (uint32_t y = 0; y < rows; ++y) {
        uint32_t row_sum = 0;
        for (uint32_t x = 0; x < cols; ++x) {
            row_sum += mask[static_cast<size_t>(y) * cols + x] ? 1u : 0u;
            integral[(static_cast<size_t>(y) + 1) * stride + x + 1] =
                integral[static_cast<size_t>(y) * stride + x + 1] + row_sum;
        }
    }
    std::vector<uint8_t> out(mask.size(), 0);
    const int side = 2 * radius + 1;
    const uint32_t required = static_cast<uint32_t>(side * side);
    for (int y = radius; y < static_cast<int>(rows) - radius; ++y) {
        for (int x = radius; x < static_cast<int>(cols) - radius; ++x) {
            const int y0 = y - radius, y1 = y + radius + 1;
            const int x0 = x - radius, x1 = x + radius + 1;
            const uint32_t sum = integral[static_cast<size_t>(y1) * stride + x1]
                               - integral[static_cast<size_t>(y0) * stride + x1]
                               - integral[static_cast<size_t>(y1) * stride + x0]
                               + integral[static_cast<size_t>(y0) * stride + x0];
            if (sum == required) out[static_cast<size_t>(y) * cols + x] = 1;
        }
    }
    return out;
}

static std::vector<float> gaussian_blur_sigma(const std::vector<float>& image,
                                              uint32_t rows, uint32_t cols,
                                              float sigma) {
    const int radius = std::max(1, static_cast<int>(std::ceil(3.0f * sigma)));
    const auto kernel = gaussian_kernel(2 * radius + 1, sigma);
    std::vector<float> out;
    separable_blur(image, out, rows, cols, kernel);
    return out;
}

static std::vector<float> multiscale_dog(const std::vector<float>& image,
                                         uint32_t rows, uint32_t cols) {
    const auto g08 = gaussian_blur_sigma(image, rows, cols, 0.8f);
    const auto g16 = gaussian_blur_sigma(image, rows, cols, 1.6f);
    const auto g32 = gaussian_blur_sigma(image, rows, cols, 3.2f);
    std::vector<float> dog(image.size(), 0.0f);
    for (size_t p = 0; p < image.size(); ++p) {
        dog[p] = std::max({0.0f, g08[p] - g16[p], g16[p] - g32[p]});
    }
    return dog;
}

static ImprovedResult extract_improved(const std::vector<float>& score,
                                       const std::vector<uint8_t>& mask,
                                       const uint8_t* gt_mask,
                                       uint32_t rows, uint32_t cols,
                                       float spacing, double threshold) {
    ImprovedResult result;
    result.threshold = threshold;
    std::vector<uint8_t> binary(score.size(), 0), seen(score.size(), 0);
    for (size_t p = 0; p < score.size(); ++p) {
        binary[p] = mask[p] && score[p] >= threshold ? 1 : 0;
    }
    const double amin = 0.01 / (spacing * spacing);
    const double amax = 1.0 / (spacing * spacing);
    std::vector<size_t> stack;
    stack.reserve(2048);
    for (uint32_t y = 0; y < rows; ++y) {
        for (uint32_t x = 0; x < cols; ++x) {
            const size_t start = static_cast<size_t>(y) * cols + x;
            if (!binary[start] || seen[start]) continue;
            seen[start] = 1;
            stack.clear();
            stack.push_back(start);
            size_t area = 0;
            uint64_t sum_x = 0, sum_y = 0;
            while (!stack.empty()) {
                const size_t p = stack.back();
                stack.pop_back();
                ++area;
                const int py = static_cast<int>(p / cols);
                const int px = static_cast<int>(p % cols);
                sum_x += static_cast<uint64_t>(px);
                sum_y += static_cast<uint64_t>(py);
                for (int dy = -1; dy <= 1; ++dy) for (int dx = -1; dx <= 1; ++dx) {
                    if (dx == 0 && dy == 0) continue;
                    const int ny = py + dy, nx = px + dx;
                    if (ny < 0 || nx < 0 || ny >= static_cast<int>(rows) || nx >= static_cast<int>(cols)) continue;
                    const size_t q = static_cast<size_t>(ny) * cols + nx;
                    if (binary[q] && !seen[q]) { seen[q] = 1; stack.push_back(q); }
                }
            }
            if (!(static_cast<double>(area) > amin && static_cast<double>(area) < amax)) continue;
            ++result.candidates;
            bool overlaps = false;
            if (gt_mask) {
                const int cx = static_cast<int>(sum_x / area);
                const int cy = static_cast<int>(sum_y / area);
                for (int yy = std::max(0, cy - 5); yy <= std::min(static_cast<int>(rows) - 1, cy + 5) && !overlaps; ++yy) {
                    for (int xx = std::max(0, cx - 5); xx <= std::min(static_cast<int>(cols) - 1, cx + 5); ++xx) {
                        if (gt_mask[static_cast<size_t>(yy) * cols + xx]) { overlaps = true; break; }
                    }
                }
            }
            if (overlaps) { ++result.tp; result.detected = true; }
            else { ++result.fp; }
        }
    }
    return result;
}

static void analyze_improved_core(const std::vector<float>& input_image,
                                  const std::vector<uint8_t>& input_mask,
                                  const uint8_t* gt_mask,
                                  uint32_t rows, uint32_t cols, float spacing,
                                  ImprovedResult (&results)[2]) {
    const auto image = robust_renormalize(input_image, input_mask);
    const auto mask = erode_mask_box(input_mask, rows, cols, 15);
    const auto deform = deformation_map(image, rows, cols);
    const auto dog = multiscale_dog(image, rows, cols);
    std::vector<float> product(image.size(), 0.0f);
    double sum = 0.0, sum2 = 0.0;
    size_t n = 0;
    for (size_t p = 0; p < image.size(); ++p) {
        product[p] = deform[p] * dog[p];
        if (mask[p]) {
            const double v = product[p];
            sum += v; sum2 += v * v; ++n;
        }
    }
    const double mean = n ? sum / n : 0.0;
    const double stddev = n ? std::sqrt(std::max(0.0, sum2 / n - mean * mean)) : 0.0;
    // 0 = balanced: mayor precision/especificidad con DoG absoluto.
    results[0] = extract_improved(dog, mask, gt_mask, rows, cols, spacing, 0.10);
    // 1 = sensitive: mayor sensibilidad/localizacion con tensor x DoG.
    results[1] = extract_improved(product, mask, gt_mask, rows, cols, spacing, mean + 40.0 * stddev);
}

#if defined(_WIN32)
#define INBREAST_MEJORADO_EXPORT extern "C" __declspec(dllexport)
#else
#define INBREAST_MEJORADO_EXPORT extern "C"
#endif

INBREAST_MEJORADO_EXPORT int analyze_inbreast_mejorado(
    const float* image, const uint8_t* mask, const uint8_t* gt_mask,
    uint32_t rows, uint32_t cols, float spacing,
    double* thresholds2, uint64_t* candidates2, uint64_t* tp2,
    uint64_t* fp2, int* detected2, double* time_ms) {
    if (!image || !mask || rows == 0 || cols == 0 || spacing <= 0.0f) return 2;
    try {
        const size_t n = static_cast<size_t>(rows) * cols;
        const std::vector<float> image_v(image, image + n);
        const std::vector<uint8_t> mask_v(mask, mask + n);
        ImprovedResult results[2];
        const auto t0 = std::chrono::steady_clock::now();
        analyze_improved_core(image_v, mask_v, gt_mask, rows, cols, spacing, results);
        const auto t1 = std::chrono::steady_clock::now();
        for (int i = 0; i < 2; ++i) {
            if (thresholds2) thresholds2[i] = results[i].threshold;
            if (candidates2) candidates2[i] = static_cast<uint64_t>(results[i].candidates);
            if (tp2) tp2[i] = static_cast<uint64_t>(results[i].tp);
            if (fp2) fp2[i] = static_cast<uint64_t>(results[i].fp);
            if (detected2) detected2[i] = results[i].detected ? 1 : 0;
        }
        if (time_ms) *time_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
        return 0;
    } catch (...) {
        return 1;
    }
}

#ifndef INBREAST_MEJORADO_LIBRARY
int main(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "Uso: deform_inbreast_mejorado <balanced|sensitive> <archivo.inbr> [archivo.inbr ...]\n";
        return 2;
    }
    const std::string mode = argv[1];
    const int selected = mode == "balanced" ? 0 : mode == "sensitive" ? 1 : -1;
    if (selected < 0) {
        std::cerr << "Modo invalido. Use balanced o sensitive.\n";
        return 2;
    }
    const size_t min_candidates = selected == 0 ? 3u : 1u;
    std::cout << "archivo,modo,filas,columnas,spacing,threshold,candidatos,min_candidatos,imagen_positiva,tiempo_ms\n";
    for (int a = 2; a < argc; ++a) {
        try {
            const InputImage in = read_input(argv[a]);
            ImprovedResult results[2];
            const auto t0 = std::chrono::steady_clock::now();
            analyze_improved_core(in.image, in.breast_mask, nullptr, in.rows, in.cols, in.spacing, results);
            const auto t1 = std::chrono::steady_clock::now();
            const double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
            const auto& r = results[selected];
            std::cout << std::filesystem::path(argv[a]).filename().string() << ',' << mode << ','
                      << in.rows << ',' << in.cols << ',' << in.spacing << ','
                      << std::setprecision(9) << r.threshold << ',' << r.candidates << ','
                      << min_candidates << ',' << (r.candidates >= min_candidates ? 1 : 0) << ','
                      << std::fixed << std::setprecision(3) << ms << '\n';
        } catch (const std::exception& e) {
            std::cerr << "ERROR," << argv[a] << ',' << e.what() << '\n';
            return 1;
        }
    }
    return 0;
}
#endif
