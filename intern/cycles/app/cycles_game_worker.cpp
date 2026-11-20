/* SPDX-License-Identifier: Apache-2.0
 * Copyright 2026 Z3WAX contributors */

/* Local, persistent Cycles host. Never accepts network connections.
 * Float output and the original integrator are retained; this is an integration
 * baseline, not a real-time or mobile renderer performance claim. */
#include <chrono>
#include <cmath>
#include <cstdint>
#include <filesystem>
#include <fstream>
#include <iostream>
#include <sstream>
#include <stdexcept>

#include "app/cycles_xml.h"
#include "device/device.h"
#include "scene/camera.h"
#include "scene/object.h"
#include "scene/scene.h"
#include "session/buffers.h"
#include "session/session.h"
#include "session/output_driver.h"
#include "util/path.h"

CCL_NAMESPACE_BEGIN

class GameOutputDriver : public OutputDriver {
 public:
  std::filesystem::path directory;
  uint64_t revision = 0;
  uint64_t preview_sequence = 0;
  Progress *progress = nullptr;
  bool written = false;
  string error;

  explicit GameOutputDriver(const std::filesystem::path &path) : directory(path) {}

  void write_render_tile(const Tile &tile) override
  {
    write_frame(tile, true);
  }

  bool update_render_tile(const Tile &tile) override
  {
    write_frame(tile, false);
    return error.empty();
  }

 private:
  void write_frame(const Tile &tile, bool complete)
  {
    if (!(tile.size == tile.full_size)) {
      error = "Expected a complete frame";
      return;
    }
    const uint32_t width = tile.size.x, height = tile.size.y;
    vector<float> pixels(size_t(width) * height * 4);
    if (!tile.get_pass_pixels("combined", 4, pixels.data())) {
      error = "Could not read combined pass";
      return;
    }
    const string filename = complete ? "frame.rgba32f" : "preview.rgba32f";
    const auto temporary = directory / (filename + ".tmp");
    std::ofstream out(temporary, std::ios::binary | std::ios::trunc);
    /* Protocol v1: little-endian uint32 width/height, uint64 revision,
     * then top-to-bottom scene-linear RGBA float32 (no tonemap or compression). */
    out.write(reinterpret_cast<const char *>(&width), sizeof(width));
    out.write(reinterpret_cast<const char *>(&height), sizeof(height));
    out.write(reinterpret_cast<const char *>(&revision), sizeof(revision));
    if (!complete) {
      ++preview_sequence;
      const uint32_t samples = progress ? progress->get_current_sample() : 0;
      const uint32_t reserved = 0;
      out.write(reinterpret_cast<const char *>(&preview_sequence), sizeof(preview_sequence));
      out.write(reinterpret_cast<const char *>(&samples), sizeof(samples));
      out.write(reinterpret_cast<const char *>(&reserved), sizeof(reserved));
    }
    for (int y = int(height) - 1; y >= 0; --y) {
      out.write(reinterpret_cast<const char *>(pixels.data() + size_t(y) * width * 4),
                std::streamsize(width) * 4 * sizeof(float));
    }
    out.close();
    if (!out) {
      error = "Could not write frame";
      return;
    }
    std::error_code ec;
    std::filesystem::rename(temporary, directory / filename, ec);
    if (ec) {
      error = ec.message();
      return;
    }
    if (complete) {
      written = true;
    }
  }
};

static Transform read_transform(std::istringstream &input)
{
  float a[12];
  for (float &v : a) {
    if (!(input >> v) || !std::isfinite(v)) {
      throw std::runtime_error("Expected 12 finite row-major transform values");
    }
  }
  const double determinant = double(a[0]) * (double(a[5]) * a[10] - double(a[6]) * a[9]) -
                             double(a[1]) * (double(a[4]) * a[10] - double(a[6]) * a[8]) +
                             double(a[2]) * (double(a[4]) * a[9] - double(a[5]) * a[8]);
  if (std::abs(determinant) < 1e-20) {
    throw std::runtime_error("Transform must be invertible");
  }
  return make_transform(a[0], a[1], a[2], a[3], a[4], a[5], a[6], a[7],
                        a[8], a[9], a[10], a[11]);
}

static void require_end(std::istringstream &input)
{
  string extra;
  if (input >> extra) {
    throw std::runtime_error("Unexpected command arguments");
  }
}

static int run(int argc, char **argv)
{
  if (argc != 7) {
    std::cerr << "Usage: cycles_game_worker SCENE.xml OUTPUT_DIR WIDTH HEIGHT SAMPLES THREADS\n";
    return 2;
  }
  const int width = std::stoi(argv[3]), height = std::stoi(argv[4]);
  const int samples = std::stoi(argv[5]), threads = std::stoi(argv[6]);
  if (width < 1 || height < 1 || width > 8192 || height > 8192 ||
      int64_t(width) * height > 16777216 || samples < 1 || samples > 1048576 ||
      threads < 1 || threads > 256 || !std::filesystem::is_regular_file(argv[1])) {
    throw std::runtime_error("Invalid render dimensions, sample/thread budget, or scene file");
  }
  path_init();
  const auto devices = Device::available_devices(DEVICE_MASK_CPU);
  if (devices.empty()) {
    throw std::runtime_error("No Cycles CPU device available");
  }
  SessionParams params;
  params.device = devices.front();
  params.background = true;
  /* Godot is the display host: enable progressive OutputDriver callbacks,
   * while background=true still finishes at the requested sample count.
   * No OpenGL context or window is created in this worker. */
  params.headless = false;
  params.samples = samples;
  params.threads = threads;
  params.pixel_size = 1;
  params.use_auto_tile = false;
  params.use_resolution_divider = false;
  params.time_limit = 0;
  SceneParams scene_params;
  scene_params.bvh_type = BVH_TYPE_DYNAMIC;
  scene_params.texture_limit = 0;
  Session session(params, scene_params);
  xml_read_file(session.scene, argv[1]);
  /* The standalone XML reader forces STATIC; restore DYNAMIC before the first
   * BVH build, otherwise transforms are baked and later object updates vanish. */
  session.scene->params.bvh_type = BVH_TYPE_DYNAMIC;
  auto *camera = session.scene->camera;
  camera->set_full_width(width);
  camera->set_full_height(height);
  camera->compute_auto_viewplane();
  Pass *pass = session.scene->create_node<Pass>();
  pass->set_name(ustring("combined"));
  pass->set_type(PASS_COMBINED);
  const std::filesystem::path directory(argv[2]);
  std::filesystem::create_directories(directory);
  auto output = make_unique<GameOutputDriver>(directory);
  auto *driver = output.get();
  driver->progress = &session.progress;
  session.set_output_driver(std::move(output));
  BufferParams buffer;
  buffer.width = buffer.full_width = width;
  buffer.height = buffer.full_height = height;
  uint64_t last_revision = 0;
  std::cout << "READY 1 " << session.scene->objects.size() << std::endl;
  string line;
  while (std::getline(std::cin, line)) {
    try {
      std::istringstream input(line);
      string command;
      input >> command;
      if (command == "quit") {
        require_end(input);
        break;
      }
      if (command == "object") {
        size_t index;
        if (!(input >> index) || index >= session.scene->objects.size()) {
          throw std::runtime_error("Invalid object index");
        }
        const Transform tfm = read_transform(input);
        require_end(input);
        Object *object = session.scene->objects[index];
        object->set_tfm(tfm);
        object->tag_update(session.scene);
        std::cout << "UPDATED " << index << std::endl;
        continue;
      }
      if (command != "render") {
        throw std::runtime_error("Unknown command");
      }
      int64_t parsed_revision;
      if (!(input >> parsed_revision) || parsed_revision <= 0 ||
          uint64_t(parsed_revision) <= last_revision) {
        throw std::runtime_error("Render revision must increase");
      }
      const uint64_t revision = uint64_t(parsed_revision);
      input >> std::ws;
      if (!input.eof()) {
        const Transform tfm = read_transform(input);
        float fov;
        if (!(input >> fov) || !std::isfinite(fov) || fov <= 0 || fov >= M_PI_F) {
          throw std::runtime_error("Invalid camera field of view");
        }
        require_end(input);
        camera->set_matrix(tfm);
        camera->set_fov(fov);
        camera->compute_auto_viewplane();
        camera->need_flags_update = true;
      }
      driver->revision = revision;
      driver->written = false;
      driver->error.clear();
      const auto start = std::chrono::steady_clock::now();
      session.reset(params, buffer);
      session.start();
      session.wait();
      if (session.progress.get_error()) {
        throw std::runtime_error(session.progress.get_error_message());
      }
      if (!driver->written) {
        throw std::runtime_error(driver->error.empty() ? "No completed frame" : driver->error);
      }
      last_revision = revision;
      const double seconds = std::chrono::duration<double>(
          std::chrono::steady_clock::now() - start).count();
      std::cout << "FRAME " << revision << " " << width << " " << height << " "
                << samples << " " << seconds << std::endl;
    }
    catch (const std::exception &error) {
      std::cout << "ERROR " << error.what() << std::endl;
    }
  }
  return 0;
}
CCL_NAMESPACE_END

int main(int argc, char **argv)
{
  try {
    return ccl::run(argc, argv);
  }
  catch (const std::exception &error) {
    std::cerr << "ERROR " << error.what() << std::endl;
    return 1;
  }
}
