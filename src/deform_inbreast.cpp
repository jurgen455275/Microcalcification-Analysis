#include <algorithm>
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iomanip>
#include <iostream>
#include <numeric>
#include <queue>
#include <stdexcept>
#include <string>
#include <vector>

struct InputImage {
    uint32_t rows{};
    uint32_t cols{};
    float spacing{};
    std::vector<float> image;
    std::vector<uint8_t> breast_mask;
};

static InputImage read_input(const std::string& path) {
    std::ifstream in(path, std::ios::binary);
    if (!in) throw std::runtime_error("No se pudo abrir " + path);
    uint32_t magic = 0;
    InputImage out;
    in.read(reinterpret_cast<char*>(&magic), sizeof(magic));
    in.read(reinterpret_cast<char*>(&out.rows), sizeof(out.rows));
    in.read(reinterpret_cast<char*>(&out.cols), sizeof(out.cols));
    in.read(reinterpret_cast<char*>(&out.spacing), sizeof(out.spacing));
    if (magic != 0x494E4252u || out.rows == 0 || out.cols == 0) {
        throw std::runtime_error("Formato INBR invalido: " + path);
    }
    const size_t n = static_cast<size_t>(out.rows) * out.cols;
    out.image.resize(n);
    out.breast_mask.resize(n);
    in.read(reinterpret_cast<char*>(out.image.data()), static_cast<std::streamsize>(n * sizeof(float)));
    in.read(reinterpret_cast<char*>(out.breast_mask.data()), static_cast<std::streamsize>(n));
    if (!in) throw std::runtime_error("Archivo INBR incompleto: " + path);
    return out;
}

static inline int clampi(int x, int lo, int hi) {
    return std::max(lo, std::min(x, hi));
}

static std::vector<float> gaussian_kernel(int size, float sigma) {
    std::vector<float> k(size);
    const int r = size / 2;
    float sum = 0.0f;
    for (int i = -r; i <= r; ++i) {
        const float v = std::exp(-(i * i) / (2.0f * sigma * sigma));
        k[i + r] = v;
        sum += v;
    }
    for (float& v : k) v /= sum;
    return k;
}

static void separable_blur(const std::vector<float>& src, std::vector<float>& dst,
                           uint32_t rows, uint32_t cols, const std::vector<float>& k) {
    const int radius = static_cast<int>(k.size() / 2);
    std::vector<float> tmp(src.size());
    for (uint32_t y = 0; y < rows; ++y) {
        const size_t base = static_cast<size_t>(y) * cols;
        for (uint32_t x = 0; x < cols; ++x) {
            float s = 0.0f;
            for (int j = -radius; j <= radius; ++j) {
                const int xx = clampi(static_cast<int>(x) + j, 0, static_cast<int>(cols) - 1);
                s += src[base + static_cast<size_t>(xx)] * k[j + radius];
            }
            tmp[base + x] = s;
        }
    }
    dst.resize(src.size());
    for (uint32_t y = 0; y < rows; ++y) {
        for (uint32_t x = 0; x < cols; ++x) {
            float s = 0.0f;
            for (int j = -radius; j <= radius; ++j) {
                const int yy = clampi(static_cast<int>(y) + j, 0, static_cast<int>(rows) - 1);
                s += tmp[static_cast<size_t>(yy) * cols + x] * k[j + radius];
            }
            dst[static_cast<size_t>(y) * cols + x] = s;
        }
    }
}

static void sobel(const std::vector<float>& src, std::vector<float>& gx,
                  std::vector<float>& gy, uint32_t rows, uint32_t cols) {
    gx.resize(src.size());
    gy.resize(src.size());
    for (uint32_t y = 0; y < rows; ++y) {
        const int ym = clampi(static_cast<int>(y) - 1, 0, static_cast<int>(rows) - 1);
        const int yp = clampi(static_cast<int>(y) + 1, 0, static_cast<int>(rows) - 1);
        for (uint32_t x = 0; x < cols; ++x) {
            const int xm = clampi(static_cast<int>(x) - 1, 0, static_cast<int>(cols) - 1);
            const int xp = clampi(static_cast<int>(x) + 1, 0, static_cast<int>(cols) - 1);
            const float a = src[static_cast<size_t>(ym) * cols + xm];
            const float b = src[static_cast<size_t>(ym) * cols + x];
            const float c = src[static_cast<size_t>(ym) * cols + xp];
            const float d = src[static_cast<size_t>(y) * cols + xm];
            const float f = src[static_cast<size_t>(y) * cols + xp];
            const float g = src[static_cast<size_t>(yp) * cols + xm];
            const float h = src[static_cast<size_t>(yp) * cols + x];
            const float i = src[static_cast<size_t>(yp) * cols + xp];
            const size_t p = static_cast<size_t>(y) * cols + x;
            gx[p] = -a + c - 2.0f * d + 2.0f * f - g + i;
            gy[p] = -a - 2.0f * b - c + g + 2.0f * h + i;
        }
    }
}

static std::vector<float> deformation_map(const std::vector<float>& image,
                                          uint32_t rows, uint32_t cols) {
    std::vector<float> smooth, gx, gy;
    separable_blur(image, smooth, rows, cols, {0.25f, 0.5f, 0.25f});
    sobel(smooth, gx, gy, rows, cols);
    std::vector<float> gxx(image.size()), gyy(image.size()), gxy(image.size());
    for (size_t p = 0; p < image.size(); ++p) {
        gxx[p] = gx[p] * gx[p];
        gyy[p] = gy[p] * gy[p];
        gxy[p] = gx[p] * gy[p];
    }
    const auto k7 = gaussian_kernel(7, 2.0f);
    std::vector<float> bxx, byy, bxy;
    separable_blur(gxx, bxx, rows, cols, k7);
    separable_blur(gyy, byy, rows, cols, k7);
    separable_blur(gxy, bxy, rows, cols, k7);
    std::vector<float>().swap(gxx);
    std::vector<float>().swap(gyy);
    std::vector<float>().swap(gxy);
    std::vector<float> deform(image.size());
    float tr_max = 0.0f;
    for (size_t p = 0; p < image.size(); ++p) tr_max = std::max(tr_max, bxx[p] + byy[p]);
    tr_max += 1e-6f;
    float def_max = 0.0f;
    for (size_t p = 0; p < image.size(); ++p) {
        const float tr = bxx[p] + byy[p];
        const float delta = bxx[p] - byy[p];
        const float det = std::sqrt(delta * delta + 4.0f * bxy[p] * bxy[p]);
        const float coh = std::clamp(det / (tr + 1e-6f), 0.0f, 1.0f);
        deform[p] = (1.0f - coh) * (tr / tr_max);
        def_max = std::max(def_max, deform[p]);
    }
    def_max += 1e-6f;
    for (float& v : deform) v /= def_max;
    return deform;
}

static size_t count_candidates(const std::vector<float>& deform,
                               const std::vector<uint8_t>& mask,
                               uint32_t rows, uint32_t cols, float spacing,
                               double k, double& mean, double& stddev, double& threshold,
                               const uint8_t* gt_mask = nullptr,
                               size_t* tp_out = nullptr, size_t* fp_out = nullptr,
                               bool* detected_out = nullptr) {
    double sum = 0.0, sum2 = 0.0;
    size_t nmask = 0;
    for (size_t p = 0; p < deform.size(); ++p) {
        if (!mask[p]) continue;
        const double v = deform[p];
        sum += v;
        sum2 += v * v;
        ++nmask;
    }
    mean = nmask ? sum / nmask : 0.0;
    stddev = nmask ? std::sqrt(std::max(0.0, sum2 / nmask - mean * mean)) : 0.0;
    threshold = std::min(0.95, mean + k * stddev);
    std::vector<uint8_t> binary(deform.size(), 0), seen(deform.size(), 0);
    for (size_t p = 0; p < deform.size(); ++p) binary[p] = deform[p] > threshold ? 1 : 0;
    const double amin = 0.01 / (spacing * spacing);
    const double amax = 1.0 / (spacing * spacing);
    size_t candidates = 0;
    size_t tp = 0, fp = 0;
    bool detected = false;
    std::vector<size_t> stack;
    stack.reserve(4096);
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
            if (static_cast<double>(area) > amin && static_cast<double>(area) < amax) {
                ++candidates;
                if (gt_mask) {
                    const int cx = static_cast<int>(sum_x / area);
                    const int cy = static_cast<int>(sum_y / area);
                    bool overlaps = false;
                    for (int yy = std::max(0, cy - 5); yy <= std::min(static_cast<int>(rows) - 1, cy + 5) && !overlaps; ++yy) {
                        for (int xx = std::max(0, cx - 5); xx <= std::min(static_cast<int>(cols) - 1, cx + 5); ++xx) {
                            if (gt_mask[static_cast<size_t>(yy) * cols + xx]) { overlaps = true; break; }
                        }
                    }
                    if (overlaps) { ++tp; detected = true; }
                    else { ++fp; }
                }
            }
        }
    }
    if (tp_out) *tp_out = tp;
    if (fp_out) *fp_out = gt_mask ? fp : candidates;
    if (detected_out) *detected_out = detected;
    return candidates;
}

#if defined(_WIN32)
#define INBREAST_EXPORT extern "C" __declspec(dllexport)
#else
#define INBREAST_EXPORT extern "C"
#endif

INBREAST_EXPORT int analyze_inbreast_cpp(
    const float* image, const uint8_t* mask, const uint8_t* gt_mask,
    uint32_t rows, uint32_t cols, float spacing, double k,
    double* mean, double* stddev, double* threshold,
    uint64_t* candidates, uint64_t* tp, uint64_t* fp,
    int* detected, double* time_ms) {
    if (!image || !mask || rows == 0 || cols == 0 || spacing <= 0.0f) return 2;
    try {
        const size_t n = static_cast<size_t>(rows) * cols;
        std::vector<float> image_v(image, image + n);
        std::vector<uint8_t> mask_v(mask, mask + n);
        const auto t0 = std::chrono::steady_clock::now();
        const auto deform = deformation_map(image_v, rows, cols);
        double m = 0.0, s = 0.0, th = 0.0;
        size_t cand_n = 0, tp_n = 0, fp_n = 0;
        bool det = false;
        cand_n = count_candidates(deform, mask_v, rows, cols, spacing, k,
                                  m, s, th, gt_mask, &tp_n, &fp_n, &det);
        const auto t1 = std::chrono::steady_clock::now();
        if (mean) *mean = m;
        if (stddev) *stddev = s;
        if (threshold) *threshold = th;
        if (candidates) *candidates = static_cast<uint64_t>(cand_n);
        if (tp) *tp = static_cast<uint64_t>(tp_n);
        if (fp) *fp = static_cast<uint64_t>(fp_n);
        if (detected) *detected = det ? 1 : 0;
        if (time_ms) *time_ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
        return 0;
    } catch (...) {
        return 1;
    }
}

#ifndef INBREAST_LIBRARY
int main(int argc, char** argv) {
    if (argc < 3) {
        std::cerr << "Uso: deform_inbreast <k> <archivo.inbr> [archivo.inbr ...]\n";
        return 2;
    }
    const double k = std::stod(argv[1]);
    std::cout << "archivo,filas,columnas,spacing,k,mean,std,threshold,candidatos,tiempo_ms\n";
    for (int a = 2; a < argc; ++a) {
        try {
            const InputImage in = read_input(argv[a]);
            const auto t0 = std::chrono::steady_clock::now();
            const auto deform = deformation_map(in.image, in.rows, in.cols);
            double mean = 0.0, stddev = 0.0, threshold = 0.0;
            const size_t candidates = count_candidates(deform, in.breast_mask, in.rows, in.cols,
                                                       in.spacing, k, mean, stddev, threshold);
            const auto t1 = std::chrono::steady_clock::now();
            const double ms = std::chrono::duration<double, std::milli>(t1 - t0).count();
            std::cout << std::filesystem::path(argv[a]).filename().string() << ','
                      << in.rows << ',' << in.cols << ',' << in.spacing << ',' << k << ','
                      << std::setprecision(9) << mean << ',' << stddev << ',' << threshold << ','
                      << candidates << ',' << std::fixed << std::setprecision(3) << ms << '\n';
        } catch (const std::exception& e) {
            std::cerr << "ERROR," << argv[a] << ',' << e.what() << '\n';
            return 1;
        }
    }
    return 0;
}
#endif
