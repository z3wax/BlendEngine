# SPDX-License-Identifier: GPL-2.0-or-later
#
# Game-focused desktop editor profile for Blender 3.6 / BlendEngine.
# Configure in a new build directory with:
# cmake -S . -B ../blendengine-game-build \
#   -C build_files/cmake/config/blendengine_game.cmake
#
# Eevee and the realtime compositor are built by Blender's draw module. Keep
# material/geometry tools, color management, HDR formats, rigging, audio and
# physics. This changes compiled features, never scene/render quality settings.
# Native Android games use the separate Godot exporter, not this desktop build.

set(WITH_BLENDER             ON  CACHE BOOL "" FORCE)
set(WITH_HEADLESS            OFF CACHE BOOL "" FORCE)
set(WITH_PYTHON              ON  CACHE BOOL "" FORCE)
set(WITH_PYTHON_SECURITY     ON  CACHE BOOL "" FORCE)
set(WITH_OPENCOLORIO         ON  CACHE BOOL "" FORCE)
set(WITH_IMAGE_OPENEXR       ON  CACHE BOOL "" FORCE)
set(WITH_IMAGE_WEBP          ON  CACHE BOOL "" FORCE)
set(WITH_BULLET              ON  CACHE BOOL "" FORCE)
set(WITH_AUDASPACE           ON  CACHE BOOL "" FORCE)
set(WITH_CODEC_SNDFILE       ON  CACHE BOOL "" FORCE)
set(WITH_IK_SOLVER           ON  CACHE BOOL "" FORCE)
set(WITH_IK_ITASC            ON  CACHE BOOL "" FORCE)
set(WITH_OPENSUBDIV          ON  CACHE BOOL "" FORCE)
set(WITH_GMP                 ON  CACHE BOOL "" FORCE)
set(WITH_OPENVDB             ON  CACHE BOOL "" FORCE)
set(WITH_BOOST               ON  CACHE BOOL "" FORCE)
set(WITH_TBB                 ON  CACHE BOOL "" FORCE)
set(WITH_DRACO               ON  CACHE BOOL "" FORCE)
set(WITH_STRICT_BUILD_OPTIONS ON CACHE BOOL "" FORCE)

# Preserve the Cycles baker used to turn procedural PBR into native UV assets.
# Optional standalone rendering, CPU compositing and film/VFX interchange.
set(WITH_CYCLES              ON  CACHE BOOL "" FORCE)
set(WITH_CYCLES_STANDALONE   OFF CACHE BOOL "" FORCE)
set(WITH_CYCLES_OSL          OFF CACHE BOOL "" FORCE)
set(WITH_COMPOSITOR_CPU      OFF CACHE BOOL "" FORCE)
set(WITH_OPENIMAGEDENOISE    OFF CACHE BOOL "" FORCE)
set(WITH_FREESTYLE           OFF CACHE BOOL "" FORCE)
set(WITH_LIBMV               OFF CACHE BOOL "" FORCE)
set(WITH_CODEC_AVI           OFF CACHE BOOL "" FORCE)
set(WITH_CODEC_FFMPEG        OFF CACHE BOOL "" FORCE)
set(WITH_ALEMBIC             OFF CACHE BOOL "" FORCE)
set(WITH_USD                 OFF CACHE BOOL "" FORCE)
set(WITH_OPENCOLLADA         OFF CACHE BOOL "" FORCE)
set(WITH_MATERIALX           OFF CACHE BOOL "" FORCE)
set(WITH_IMAGE_CINEON        OFF CACHE BOOL "" FORCE)

# Offline simulation and document export. Keep OpenVDB volume assets readable.
set(WITH_MOD_FLUID           OFF CACHE BOOL "" FORCE)
set(WITH_MOD_OCEANSIM        OFF CACHE BOOL "" FORCE)
set(WITH_NANOVDB             OFF CACHE BOOL "" FORCE)
set(WITH_HARU                OFF CACHE BOOL "" FORCE)
set(WITH_POTRACE             OFF CACHE BOOL "" FORCE)
set(WITH_IO_GPENCIL          OFF CACHE BOOL "" FORCE)
set(WITH_INSTALL_COPYRIGHT   ON  CACHE BOOL "" FORCE)
