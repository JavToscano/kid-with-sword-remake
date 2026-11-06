# kid with sword remake: Ocarina of Time (Switch 2) as a native iPhone and Mac app

This fork of [nxnative](https://github.com/seedds/nxnative) runs The Legend of Zelda: Ocarina of Time (Switch 2, title ID `0400486024DEC000`) natively on iOS and macOS. This page describes how it was built: where the code came from, what was changed and why, every build step, what was tested, and what is still open. It covers the state as of 2026-11-06.

**Nothing from the game is in this repository.** You need your own dump of the game; the build reads its files from your dump folder and writes the apps on your own Mac.

## The game version: the v1 dump

Everything here was built and tested with the **v1 dump**: the base game (v0) plus update **v131072**. The game profile (`dm/games/0400486024DEC000/game.tsv`) has one build row, `v131072`, and packs that version; other updates are untested.

The dump folder the build was run on looks like this (an unpacked dump, no `prod.keys` needed for a Switch 2 game):

```
kid with sword game/
  base/
    exefs/      the base game's code (main, subsdk0, sdk, main.npdm)
    romfs/      the base game's files
  updates/
    131072/
      exefs/    the v131072 update's code
      romfs/    the v131072 update's files
```

A `.nup` container of the same files works too ([Switch 2 games](../../README.md)).

## Builds

Every iPhone build is numbered; its file is `OcarinaOfTime-V<n>.ipa` (the first two had other names).

| Build | IPA | What changed | Tested |
|---|---|---|---|
| V1 | `OcarinaOfTime.ipa`, 26.9 GB, game files inside | The first IPA: the merged fixes, fixed 720p, MetalFX upscaling, texture release level 2, the increased memory limit | iPhone 18 Pro: boots, plays the title and opening movie, then stops right after the opening cutscene |
| V2 | `OcarinaOfTime-split.ipa`, 2.7 GB, game files copied once | Split IPA; the encode-thread crash after the opening cutscene fixed | Mac: the crash reproduced and fixed. iPhone 18 Pro: plays past the cutscene, but about 38 fps after it, with 0.2-1.3 s freezes when new shader pipelines compile |
| V3 | `OcarinaOfTime-V3.ipa`, 3.0 GB, split | Metal 4 pipelines on the iPhone (profile key `pso_mtl4 on`): the pipeline prebuild on the first start and hybrid pipelines, so draws no longer wait for pipeline compiles | iPhone 18 Pro: fewer stutters, up to about 40 fps. The first start prepares about 30,500 pipelines once |
| V4 | `OcarinaOfTime-V4.ipa`, split | A **Frame rate** setting (30 / 60) in the launcher, through a frame step patch of the game's own frame-rate controller: 30 fps holds every frame 33.3 ms at full game speed. The touch gamepad starts in the 3D layout, whose right stick turns the camera | Mac: 30 and 60 both run, no crash, 30 fps frame time p50 33.3 / p95 34-36 ms. Not yet on the iPhone |
| V5 | `OcarinaOfTime-V5.ipa`, 3.0 GB, split | The launcher's **Console mode** picks the resolution: handheld 1280 × 720, docked 1951 × 1098 (the game's nearest size to 1080p; see [Resolution](#resolution)). The black world with the MetalFX upscaler at other resolutions fixed | Mac: both modes render at those sizes, no crash. Not yet on the iPhone |
| V6 | `OcarinaOfTime-V6.ipa`, 3.2 GB, split | Upstream and fork performance work (see [Where the code comes from](#where-the-code-comes-from)): draws that write depth no longer end render passes, raw-memory lookups start from the entry they chose last, back-to-back compute dispatches run side by side, fewer render-pass splits for grass; crash fixes (the ocarina, iOS 26.0 with Metal 4, later areas' memory maps); a fixed frame rate (the launcher's 30 or 60, no automatic step to 30, no heat cap) | Mac (MacBook Air M5, 720p handheld, Kokiri Forest): GPU p50 18-19 → 13.6-16 ms, frame p50 16.6-17.0 ms, 0 dropped frames in 4 of 5 windows. Not yet on the iPhone |
| V7 | `OcarinaOfTime-V7.ipa`, 3.2 GB, split | An 8 GB alias region (`mem_alias 0x200000000`, `mem_reserve 0x468000000`) for the game's streaming allocator: with 2.38 GB the loader retried what did not fit and the `OptimizeChangeBanc` thread spun a whole core, heating the iPhone into thermal state "serious" within a minute | Mac: the thread sleeps, process CPU 308% → 168%. iPhone: V6 held 60 for about 20 s of gameplay, then iOS moved the game to its efficiency cores; V7 not yet on the iPhone |
| V8 | `OcarinaOfTime-V8.ipa`, 3.2 GB, split | Four submit-thread savings from Xipzer (5-30% less submit CPU on the Mac), the GPU architecture in the log (`applegpu_g19p` on the iPhone 18 Pro) and the **Forest** touch-control theme (launcher setting `Touch controls style`) | iPhone 18 Pro: 60 fps for about 45 s, then 33-46 fps once iOS lowers the CPU clock at thermal state "fair" (GPU 12-14 ms a frame, so the limit is the CPU clock, not the GPU) |

## What you need

- **A Mac with Apple silicon.** Built and tested on a fanless MacBook Air M5 (10-core GPU) with 16 GB. macOS 26.6 or later and Xcode 27.2, as in the [README](../../README.md).
- **Homebrew tools:** `xcodegen`, `zstd`, the .NET SDK 10 (the shader translator), and Python. The IPA was built with Homebrew's **Python 3.15** (`/opt/homebrew/bin/python3.15`), whose standard library has `compression.zstd`; with Python 3.12 or 3.13 the script also needs `backports.zstd`. The Python running the script needs `lz4`, `capstone` 5.x and `fonttools` (see the header of `scripts/build_ipa_from_nsp.py`).
- **`zbic` 1.0.1.post1** (Nintendo's ZBIC compression of Switch 2 code modules), installed into the user's site of that Python:
  ```sh
  /opt/homebrew/bin/python3.15 -m pip install --user --break-system-packages zbic==1.0.1.post1
  ```
- **`zstandard`**, only for the resolution tool (`scripts/oot_res_overlay.py`), for example in a venv: `python3 -m venv venv && venv/bin/pip install zstandard`.
- **Disk space:** about 80 GB for the build folder (the extracted game, its RomFS image and the compiled shaders), plus 3 GB (split) or 27 GB (bundled) for the IPA.
- **For the iPhone:** an iPhone with iOS 26 or later (tested: iPhone 18 Pro) and a sideloader (tested: LiveContainer; SideStore or AltStore also work for an unsigned IPA).

## Where the code comes from

1. **seedds/nxnative `main`**, the upstream project.
2. **The Ocarina of Time branch** (`game-ocarina-of-time`, 192 commits on top of `main`): the game's profile (#1299), its SDK 22 services, NVN2 task and mesh shaders, Ampere instructions (F2IP, ATOMG.CAS, float atomic adds), the raw global memory pool table, the NDSR / NDVE packs, render conditions (agl's conditional clears), and the bindless pool-table patching that took Kokiri Forest from 46-49 ms to 16-21 ms a frame.
3. **Upstream pull requests merged into it** (3-way merges, conflicts resolved by hand):

   | PR | What it does |
   |---|---|
   | [#1343](https://github.com/seedds/nxnative/pull/1343) | Live shader inputs kept by dead-code removal: fixes the foliage jitter (translator rebuilt, shader chain `dce350aafbe2`) |
   | [#1368](https://github.com/seedds/nxnative/pull/1368) | Mesh pipelines built before their first draw: no missing foliage objects |
   | [#1446](https://github.com/seedds/nxnative/pull/1446) | A null memory pool or buffer gets 0 / NULL from the NVN getters instead of a host crash (Hyrule Field) |
   | [#1447](https://github.com/seedds/nxnative/pull/1447) | GPU-written texture ranges (no terrain holes) and the opt-in texture release |
   | [#1394](https://github.com/seedds/nxnative/pull/1394) | The raw global memory pool table lists only pools the game took a buffer address in |
   | [#1439](https://github.com/seedds/nxnative/pull/1439) | A storage takeover checks the live texture objects in one lookup |
   | [#1455](https://github.com/seedds/nxnative/pull/1455) | Shared textures no live object resolves to are retired when GPU memory runs short (the freeze after the talk with Saria) |
   | [#1393](https://github.com/seedds/nxnative/pull/1393) | Profile key `pool_skip_retired`: a finalized texture's ID gets the dummy instead of its texture made again (out of GPU memory at a scene change) |

   Since V6, also from upstream and from the Ocarina of Time fork **[The Mighty Green Kokiri Kid](https://github.com/Aznracer/Mighty-Green-Kokiri-Kid)**, which shares this tree's pool-table layout:

   | Change | Source | Effect |
   |---|---|---|
   | A pool draw that writes depth no longer counts as reading it | [#1430](https://github.com/seedds/nxnative/pull/1430) (via the fork, `5cb7d718`) | Render passes stay open: load-all store-all passes 132 → 66-69 a frame. The largest GPU saving here |
   | Raw global memory lookups start from the entry they chose last | upstream `0f510fd5` ([#1464](https://github.com/seedds/nxnative/pull/1464)), merged by hand into this tree's table layout | About 2 ms of GPU a frame (upstream's measurement); translator rebuilt, chain `a093642c4546` |
   | The game's compute dispatches with no barrier between them run side by side | fork `5208584a` (profile key `dispatch_overlap on`) | About 2 ms docked (the fork's measurement) |
   | Indirect draw conversions survive writes that hold none of their records | fork `64a114a5` | Grass splits 2 render passes a frame, not 6 |
   | Compute pipelines from the pipeline archives | [#1522](https://github.com/seedds/nxnative/pull/1522) | No compile at an effect's first dispatch |
   | Shader-code pools no longer resident | [#1484](https://github.com/seedds/nxnative/pull/1484) | 334 MB less GPU memory |
   | The ocarina's input stream | [#1527](https://github.com/seedds/nxnative/pull/1527) | No crash at the first note (Door of Time) |
   | The Metal 4 specialization descriptor owned once | upstream `88c7e03f` | No crash before the first frame on iOS 26.0 |
   | Damaged RomFS files served as a substitute | [#1530](https://github.com/seedds/nxnative/pull/1530) | For dumps with three damaged textures (this one has none) |
   | `mem_map_limit on` | fork `9f6ad246` | No crash entering Hyrule Castle, Kakariko Village and Death Mountain (reported in #1444) |

   Since V9, from the **oot2** branch of [nxnative-penis6](https://git.eden-emu.dev/penis6/nxnative-penis6/src/branch/oot2) (the Mighty Green Kokiri Kid fork's base, 9 newer commits):

   | Change | Source | Effect |
   |---|---|---|
   | An encoder's end barrier flushes to the device only | oot2 `475d7b87` | Fewer full barriers between the game's compute encoders |
   | Resolution families take every GPU-written compressible 2D image | oot2 `b8838d3b` | More render targets share one resolution family |
   | A draw that samples its depth attachment after an earlier draw wrote it ends the pass first | oot2 `d8bca8ae` | No black blocks where an effect reads depth |
   | Raw global memory lookups keep the last entry's range and delta in private words | oot2 `6951110c`, merged into this tree's table layout | A read inside the kept entry needs no read of the pool table (skinned vertex shaders: 759 such reads a vertex, about 7 ms of a frame in Hyrule Castle Town, oot2's measurement) |
   | Four adjacent raw reads become one 16-byte load (`dmsh_wide.raw_fours`) | oot2 `eab8cca5`, with this tree's hint tag (the chunk, not chunk + 1) | Hyrule Castle Town 17.7 → 15.5-16.0 ms of GPU a frame (oot2's measurement) |

   Shader chain `8c88ed8cda05`. Not taken from oot2: `f09e6c8c` (needs #1453's render-target heap) and `1837defd` (the texture CPU rewrite, built on oot2's NDVE direct draws).

   Not taken: [#1468](https://github.com/seedds/nxnative/pull/1468) (needs upstream main's submission timing), the fork's raw-load quads (about 0.4 ms, another translator change). Upstream main itself was not merged: its Ocarina of Time profile is another line (docked by default, other shader groups, no texture release or MetalFX chain), so the changes above were taken one by one.

   Not merged: [#1427](https://github.com/seedds/nxnative/pull/1427) (needs `main`'s newer write-log code), [#1405](https://github.com/seedds/nxnative/pull/1405) (shared raw-memory lookups), [#1453](https://github.com/seedds/nxnative/pull/1453) (render-target placement heap) and the frame-pacing parts of [#1444](https://github.com/seedds/nxnative/pull/1444).

## What this fork adds

| Change | Files | Why |
|---|---|---|
| Profile key `tex_release` (`off` / `1` / `2`, `DM_GAME_TEX_RELEASE`), level 2 for this game | `dm/games/game.py`, `dm/games/0400486024DEC000/game.tsv`, `dm/gfx/nvn/nvn_mtl.m` (`rel_mode`) | The guest copy of a texture's storage is given back once its GPU copy exists: level 1 for `CPU_NO_ACCESS` pools, level 2 also for CPU-visible pages not written since their upload. Kokiri Forest peak footprint 7.07 → 5.2 GB with the iPhone's guest files. A texture made again over released storage is copied on the GPU from the one released there |
| Released storage inside anonymous pools even with guest memory in files | `dm/host/hle_svc.c` (`dm_guest_range_in_files`), `dm/gfx/nvn/nvn_dirty.c` | On iOS guest memory lives in files; the memory pools moved to anonymous memory could not be released before |
| Game file replacements in the IPA | `dm/ios/tools/build_ipa.sh`, `dm/ios/tools/stage_resources.sh`, `dm/ios/Sources/main.m` | A `romfs_overlay` folder beside the RomFS image goes into the app; `main.m` sets `DM_ROMFS_OVERLAY` to it. Used for the fixed 720p resolution |
| Game file replacements in the Mac app | `dm/mac/pack_app.py` (`--romfs-overlay`), `dm/mac/launcher.c`, `scripts/build_ipa_from_nsp.py` | The Mac app carries `Resources/romfs_overlay` (from `romfs_overlay_mac` beside the RomFS, else `romfs_overlay`); the launcher sets `DM_ROMFS_OVERLAY` |
| Black world with the MetalFX upscaler at the game's own resolution fixed | `dm/gfx/nvn/nvn_mtl.m` (`dispatch`, the upscaler chain) | `DM_UPSCALER=metalfx` skips the first stages of the game's upscale chain and draws its last stage (the profile's `upscaler_chain`) with MetalFX. At the game's own dynamic resolution (up to 1440 × 810, no 720p file) the chain ends at other stages (`fa3033d05c0a41d6`, `b106afba1a18faa9`), which read the skipped stages' outputs: the 3D world was black under the HUD. Such a chain now falls back to the game's own chain from the next frame on. Reported from another M5 Mac's app built from V3 |
| 30 / 60 fps frame step | `dm/games/0400486024DEC000/patches.py` (`FRAME_STEP`), `game.tsv` (`fps_target 60`) | The game's frame-rate controller picks its interval and fps from the host's step, so the launcher's Frame rate setting works and 30 fps runs at full speed. See [Frame rate](#frame-rate) |
| Resolution by console mode | `dm/host/hle_fs.c` (`rom_overlay_set`) | An overlay folder's `handheld/` or `docked/` subfolder comes first for the console mode at start, so the launcher's Console mode switches between 720p and 1080p. Added in V5 |
| Resolution tool | `scripts/oot_res_overlay.py` | Writes the modified resolution table (below) |
| iPhone crash after the opening cutscene fixed | `dm/gfx/nvn/nvn_rec.h` | The iPhone records Metal commands on a separate thread (`DM_NVN_ENC_THREAD`, on by default on iOS); its recorder had no stand-in for `drawMeshThreadgroupsWithIndirectBuffer:…`, the indirect task / mesh draw the game first issues after the opening cutscene, so the app stopped (`FATAL deferred encoding`). The draw is now recorded (`RO_R_MESH_IND`) and replayed |
| iOS SDK build fix | `dm/host/hle_svc.c` | `#include <mach/mach_vm.h>` removed: the iOS SDK rejects it (`vm_remap` comes from `mach/mach.h`) |
| Per-dispatch compute timings | `dm/gfx/nvn/nvn_mtl.m` (`DM_NVN_GPUPROF_CS`) | Diagnostics: GPU time of each compute shader, summed by shader key |

## Game profile settings

`dm/games/0400486024DEC000/game.tsv` holds the game's defaults; the build turns them into `game_profile.h`. The ones that matter for this port:

| Key | Value | What it does |
|---|---|---|
| `op_mode` | `handheld` | Console mode at start, as the iPhone runs it. The launcher's **Console mode** setting (`DM_OPMODE`) changes it |
| `render_cond` | `on` | agl's conditional depth clears (without it Kokiri Forest is a white scene) |
| `gmem_skip` | `on` | Compressible, shader-code and GPU no-access pools stay out of the raw memory pool table |
| `pool_skip_retired` | `on` | #1393 |
| `tex_release` | `2` | This fork; see above |
| `tex_soft` | `on` | Large block-compressed textures without their finest level on the GPU |
| `rt_drop` | `off` | Render-target stand-ins saved memory but made objects pop and sway |
| `rt_alias` | `off` | Render-target heap aliasing: glitches |
| `gpu_timestamps` | `segment` | Dynamic resolution reads the GPU time between the game's timestamp reports |
| `pso_mtl4` | `on` | Render pipelines through Metal 4 on the iPhone, as on the Mac: the launcher's pipeline prebuild builds the pipeline bases once on the first start (a wait of a few minutes) and keeps them, and hybrid pipelines draw with a ready base instead of waiting. Without it every first-used pipeline compiled on the submit thread (V2: 0.2-1.3 s freezes at the cutscene transitions). The launcher's **Metal 4 pipelines** setting turns it off. Added in V3 |
| `dispatch_overlap` | `on` | Back-to-back compute dispatches run side by side. Added in V6 |
| `mem_reserve`, `mem_alias` | `0x468000000`, `0x200000000` | 17.6 GB of guest address space with an 8 GB alias region for the streaming allocator (was 12 GB and 2.38 GB). Changed in V7 |
| `mem_map_limit` | `on` | A map past the application pool fails as on Horizon; without it the game crashes entering some later areas. Added in V6 |
| `fps_target` | `60` | Turns on the frame step and the launcher's **Frame rate** setting (30 / 60, default 60). Added in V4; see [Frame rate](#frame-rate) |
| `pad_layout` | `full` | The iPhone's touch gamepad starts in the 3D layout: D-pad, L3 / R3, and a right stick that is not drawn (a drag in the right third of the screen) for the camera. The simple layout has no right stick. A layout picked in the game menu (the gear at the top centre) is kept. Added in V4 |
| `upscaler_chain` | (four shader keys) | `DM_UPSCALER=metalfx` replaces the game's NDSR upscale chain with MetalFX |

## Resolution

The render resolution comes from the game's own files: `Pack/Bootup.Nin_Ounce_NVN2.pack.zs` → `System/GameGraphics/ModelSceneExtensionParam/Default.game__gfx__ModelSceneExtensionParam.bgyml`. Its `ResolutionParam` (a hash-keyed BYML dictionary, node type `0x20`) has one base resolution per mode, with a final image of the same size:

| Mode | Base resolution in the table | What the game shows |
|---|---|---|
| Handheld | 1920 × 1080 | 1920 × 1080 |
| Docked | 2560 × 1440 | 2048 × 1152 (a crop of a 2560 × 1440 swap chain) |

`DynamicResolutionParam` has the dynamic-resolution levels that multiply the base: `ResolutionReduceScale` 0.75, 0.711, 0.667, 0.622, 0.583, 0.533, 0.5, 0.445, 0.372, 0.333, with `LoadThreshold` 95. So the game, unchanged, renders at most 1440 × 810 handheld and 1536 × 864 docked, and steps down under GPU load. Docked sizes come in steps of about 45 pixels, measured on the Mac: scale 0.75 → 1536 × 864, 0.90 → 1862 × 1048, 0.92 → 1906 × 1072, 0.9375 → 1951 × 1098 (0.9254 still gives 1906 × 1072), so 1920 × 1080 itself is not one of them.

`scripts/oot_res_overlay.py` writes a copy of that pack with new levels; the RomFS image is not changed, the copy is served over it (`DM_ROMFS_OVERLAY`):

Each overlay folder may hold a `handheld/` and a `docked/` subfolder; the host serves the one for the console mode at start (`hle_fs.c` `rom_overlay_set`, `DM_OPMODE`, the launcher's **Console mode**) before the folder itself. Since V5 both the iPhone and the Mac app use:

| Mode | Command | Renders |
|---|---|---|
| Handheld | `oot_res_overlay.py RomFS.img romfs_overlay/handheld 0.666667 - flat` | 1280 × 720 |
| Docked | `oot_res_overlay.py RomFS.img romfs_overlay/docked 0.9375 - flat` | 1951 × 1098 (the nearest size at or above 1080 lines) |

On the MacBook Air M5 docked cost about the same GPU time as handheld 720p in the same session (16.5-20 ms against 19 ms): the game draws some things more cheaply docked, its shadow maps for example (1520 × 1520).

`flat` sets every level to the same scale, so the resolution never changes and the game never makes a new set of render targets.

## Frame rate

The game has its own frame-rate controller in `main` (v131072: `main+0x3b4ef60`, called once a frame), of the same Nintendo EPD engine family as Donkey Kong Bananza's. From the measured frame time it picks a vsync interval between two limits in its config, with hysteresis, stores it (config +0x48) with fps = 60 / interval (+0x58), and at `main+0x3b4f074`, where its paths meet, hands them on: +0x58 to `setFrameRate` (`main+0x4dc0f0`, through `main+0x3b4f160`) and +0x48 to the framework's `setInterval` (`main+0x346c5c0`), which sets the window's present interval and the framework's fps. Interval 2 is the game's own 30 fps mode, with game time stepping by the interval.

Before V4 the game never changed its interval: in every Mac run and both iPhone logs (the opening movie and cutscene included) it stayed at 1. Unlike Bananza, which drops itself to 20 fps in its cutscenes, no cutscene or load cap of the game's own was seen; areas past Kokiri Forest are unchecked.

V4's frame step (`patches.py` `FRAME_STEP`, `patch_nso.py` "Frame step in whole vsyncs"): a stub at `main+0x3b4f074` replaces the interval and fps with the host's step (state page +0x20) while a target is set (state +0x0, the launcher's **Frame rate** / `DM_FPS_TARGET`), and counts the vsyncs stepped (+0x30). The host decides the step and holds each frame that long (`hle_nvn.c` `fstep_tick`):

- **60:** one vsync a frame; a late frame is held two vsyncs and the game steps two for it, so game time follows real time.
- **30:** two vsyncs (33.3 ms) a frame. After a hitch (an area load) the host holds a few frames three vsyncs to catch up (10 times in 55 s on the Mac, around loading).

Since V6 the frame rate is fixed: the app's settings file has `DM_FPS_HOLD=off`, so the launcher's 60 holds every frame one vsync and 30 two, never longer, and `DM_THERMAL_CAP=0`. A late frame at 60 is shown late rather than held, and the game steps by the vsyncs that passed, so game speed stays right: the Mac measured `game time 33.25 s in 33.28 s (0.999 of real time)` with every frame held one vsync.

Two host caps come with the frame step: on the iPhone, while iOS reports the thermal state "serious" the host holds 30 fps until it has been "fair" for 30 s (`DM_THERMAL_CAP=0` turns this off); and while a pre-rendered movie plays the host holds 30 fps (`hle_nvn.c` `fps_step_cap`). The game's movies are 1920 × 1080 AV1; whether they keep their speed under that cap is not yet measured.

Not yet checked: game speed at 30 fps by the host's measurement (logged after 60 s of frames: `frame step: game time … of real time`). Some AI code reads a fixed 1/60 s base time step (`QueryGetBaseDeltaTime`, a constant read from 252 places); if it does not scale with the step, characters would move at half speed at 30 fps. A short look on the Mac showed nothing wrong.

## Building, step by step

The commands below use `G` for the dump folder and `B` for the build folder (`$G/0400486024DEC000_build`, the default), run from the repository's root:

```sh
G=~/Desktop/"kid with sword game"
B="$G/0400486024DEC000_build"
PY=/opt/homebrew/bin/python3.15
```

### 1. Mac development build

```sh
$PY scripts/build_ipa_from_nsp.py "$G" --platform mac --work-dir "$B" --keep-extracted
```

This extracts the game into `$B/extract/v131072` (ExeFS, a 26.2 GB `RomFS.img`), rewrites the code modules, splits out the 42,854 shaders, builds the Mac shader libraries (42,853 translate; one fails, its reason is at the end of `$B/logs/dmsh_build.log`) and the Mac host `$B/tools/dmhost`. The full shader build is the long part of a first run (upstream measured about 40 minutes on an M5 Pro); later runs reuse every stage whose inputs did not change. It prints the command that runs the game on the Mac, in this form:

```sh
cd "$B/run" && DM_ROOT="$B" DM_ROMFS="$B/extract/v131072/RomFS.img" DM_SAVE="$B/run/save" DM_TEMP="$B/run/temp" \
  DM_MSL_DIR="$B/shader/cache" DM_FONT_DIR="$B/font" DM_NVN_SHMAP="$PWD/dm/games/0400486024DEC000/shader_map.tsv" \
  DM_LANG=en-US DM_WINDOW=1 DM_AUDIO=1 DM_PSO_PAIRS="$B/shader/pso_pairs.tsv" "$B/tools/dmhost" "$B/patched_v131072"
```

(Use the exact command the script prints; `DM_NVN_SHMAP` is the profile's `shader_map.tsv` in your checkout.)

### 2. The resolution files

```sh
V="$B/extract/v131072"
venv/bin/python scripts/oot_res_overlay.py "$V/RomFS.img" "$V/romfs_overlay/handheld" 0.666667 - flat   # 1280x720
venv/bin/python scripts/oot_res_overlay.py "$V/RomFS.img" "$V/romfs_overlay/docked" 0.9375 - flat      # 1951x1098
```

`build_ipa.sh` packs `romfs_overlay` into the IPA, and the Mac app takes it too (or `romfs_overlay_mac` beside it, when that exists).

### 3. The iPhone settings file

An environment file baked into the app as `dm/env.txt` (one `KEY=VALUE` per line):

```
# baked into the iPhone app (dm/env.txt)
DM_UPSCALER=metalfx
# fixed frame rate: the launcher's Frame rate is used as set (60 = one vsync a frame, 30 = two), no automatic step to 30 on late frames and no heat cap
DM_FPS_HOLD=off
DM_THERMAL_CAP=0
```

Saved here as `ios_env.txt` in a work folder. The Mac app takes its own, `mac_env.txt`: the same `DM_UPSCALER` and `DM_FPS_HOLD` lines and `DM_ALIAS_SIZE=0x200000000` (see [Known issues](#known-issues-and-open-work)).

### 4. The iPhone IPA

Split (recommended: a 2.7 GB IPA, the game files copied to the phone once):

```sh
$PY scripts/build_ipa_from_nsp.py "$G" --work-dir "$B" --env-file ios_env.txt --keep-extracted \
  --romfs separate --gpu none -o "$G/OcarinaOfTime-V6.ipa"
```

Bundled (one 26.9 GB IPA with the game files inside; some sideloaders cannot take a file this large):

```sh
$PY scripts/build_ipa_from_nsp.py "$G" --work-dir "$B" --env-file ios_env.txt --keep-extracted
```

Both are unsigned and ad-hoc signed with the app's entitlements, including `com.apple.developer.kernel.increased-memory-limit`; the sideloader re-signs them. Bundle ID `org.nxnative.0400486024dec000`, minimum iOS 26.0. The iPhone shaders are built once and reused; a repeat build took 2.5 minutes (split) to 8 minutes (bundled), mostly packing.

The IPA has no icon (a dump folder has no control data). `--gpu none` leaves out the pipeline archive made offline, because the architecture name of the iPhone 18 Pro's GPU is not known here (`--gpu g18p` would build one for the A19 / A19 Pro); with `pso_mtl4 on` the phone builds the pipeline bases itself on the first start and keeps them. Turning Metal 4 on also makes the iPhone shader stage compile the pulling libraries the hybrid pipelines need, so the first build after it recompiles the iPhone shaders (about 14 minutes on the MacBook Air M5). The frame-rate counter is on; `DM_SHOW_FPS=0` in the app's `Documents/env.txt` turns it off.

### 5. Installing on the iPhone

1. Sideload the IPA.
2. Split IPA only: copy the game image `$B/extract/v131072/RomFS.img` into the app's **Documents** folder as `romfs.img`, once. Either through the Files app or Finder (the app's Documents folder is shared), or over USB with:
   ```sh
   scripts/push_romfs.sh <device UDID> org.nxnative.0400486024dec000 "$B/extract/v131072/RomFS.img"
   ```
   The app carries the image's identity (`romfs.id`) and only uses a complete image of that version, so a copy cut off halfway is never used. Copy it again only when the game version or the extraction changes.
3. Start the game. Its log is `Documents/log.txt`.

### 6. The Mac app with the launcher

```sh
$PY scripts/build_ipa_from_nsp.py "$G" --platform mac-app --work-dir "$B" --env-file mac_env.txt --keep-extracted \
  -o "$G/Ocarina of Time.app"
```

Make the Mac's resolution file first (step 2, `romfs_overlay_mac`, or `romfs_overlay` for 720p); without one the game renders at its own dynamic resolution. Builds before the upscaler-chain fix showed a black world with `DM_UPSCALER=metalfx` (from `ios_env.txt`) at that resolution; on such a build, add `DM_UPSCALER=game` to `~/Library/Application Support/nxnative/0400486024DEC000/env.txt`, which wins over the app's own `env.txt`.

A self-contained, double-clickable app: the game files are APFS clones of the build's (no extra 26 GB on the same volume), the Mac shaders, a pipeline archive made with `metal-tt` for this Mac's GPU, and the resolution files. Its settings window opens before the game starts; **Console mode** picks Handheld (1280 × 720) or Docked (1951 × 1098), **Frame rate** 30 or 60. Saves go to `~/Library/Application Support/nxnative/0400486024DEC000/`, the log to `~/Library/Logs/nxnative/0400486024DEC000.log`.

## Tests and results

All on the v1 dump (v131072). Mac runs were capped by a memory guard (the game killed past a 9 GB footprint); scripted runs press only A, to load the save, and the player does the rest.

| Run | Where | Result |
|---|---|---|
| Unit tests (`dm/gfx/tests`, `GAME=010015100B514000`) | Mac | The merged PRs' tests (t_dirty_discard, t_gmem_marks, t_alias_takeover, t_alias_retire, t_pool_retired, t_cpu_storage) and t_cpu_tex, t_feedback all pass |
| Play test after the merges | MacBook Air M5, Kokiri Forest | Mostly 60 fps outdoors: frame p50 16.6-16.9 ms, GPU about 17 ms; peak footprint 9.45 GB with guest memory in RAM |
| Guest memory in files (`DM_GUEST_FILE=1`, as iOS does it) | Mac | Kokiri Forest peak 7.07 GB |
| `tex_release 2` | Mac, 4-minute play test | Peak 5.53 GB (5.19 GB in a second run), 2.4 GB released, no textures lost, no new errors |
| First iPhone run (bundled IPA, LiveContainer) | iPhone 18 Pro | Boots; title and opening movie mostly at 60 fps (p99 16.67 ms), footprint about 2 GB at the title; then stopped at frame 9911, right after the opening cutscene (`FATAL deferred encoding: DmRecEnc has no stand-in for -drawMeshThreadgroupsWithIndirectBuffer:…`) |
| The crash reproduced on the Mac | Mac, `DM_NVN_ENC_THREAD=1`, the old host | Same `FATAL` line |
| The fix | Mac, `DM_NVN_ENC_THREAD=1 DM_GUEST_FILE=1`, 150 s | No error past the same point |
| V2 on the iPhone | iPhone 18 Pro, LiveContainer, about 2,400 frames | No crash. Before the cutscene 60 fps; after it frame p50 19-26 ms (about 38 fps), GPU p50 15-22 ms rising as the phone warmed, the submit thread 9-15 ms of CPU a frame. Every long frame (0.2-1.3 s) was a pipeline compile (fixed in V3) or an area load (610 MB of textures). The share of CPU time on performance cores fell from about 50% to 0% during the run; the phone reported thermal state 1 from the start |
| Mac play test with the fix | Mac, 73 s until the window was closed | No crash; frame p50 16.5-17.9 ms, a few 90-127 ms loading hitches; peak footprint 7.4 GB |
| Mac at 720p, same save, standing still: the 15:21 host against the current one | MacBook Air M5, 130 s each | The same speed (GPU 20-23 ms right after entering gameplay, settling to 17-19 ms): no regression. The Mac was slower than in the afternoon's runs after about 1.5 hours of shader builds (likely heat; no thermal warning recorded) |
| MetalFX upscaler at the game's own 1440 × 810 (another player's Mac app, reproduced here) | Mac, frame dumps (`DM_NVN_TEXDUMP`) | Before: the scene drew at 1440 × 810, the final 1920 × 1080 picture was black but for the HUD. After the fix: the world draws; at 720p MetalFX still draws the last stage |
| V5 console modes | Mac, 720p handheld and docked at several scales, 80-100 s each | Handheld 1280 × 720, docked 1951 × 1098 at 0.9375, the mode's file served (`fs rom overlay: … for the docked mode`), no crash. With the Mac hot (GPU 19-20 ms) the 60 fps setting held a steady 30 (two vsyncs a frame) in both modes |
| The busy thread and the alias region | Mac, V6 host, 150 s each, A presses only | 2.38 GB: `alias region mapped up to +2.26 GB`, `OptimizeChangeBanc` 997-998 ms/s in 20 windows, CPU 308%. 8 GB: mapped up to +4.5-4.75 GB, the thread asleep (`sample`: `dm_guest_sleep_ns`), CPU 168% |
| V6 on the iPhone | iPhone 18 Pro, LiveContainer | Frame p50 16.5-16.8 ms and GPU 12.3-14.4 ms in gameplay for about 20 s; thermal state "serious" at launch and again at 54 s, then the fast-core share fell 55% → 19% and the frame took 24 ms. No crash |
| V6 on the Mac, same scene, before and after the fork's GPU changes | MacBook Air M5, 720p handheld, MetalFX, fixed 60, 150 s each | GPU p50 17.9-19.0 → 13.6-16.1 ms; frame p50 31-35 → 16.6-17.0 ms; load-all store-all passes 132 → 66-69; on screen 0 dropped frames in 4 of 5 windows (the fifth: the 0.8 s area load) |
| V4 frame step, 60 fps | Mac, 720p, 150 s | No crash. Kokiri Forest frame p50 16.6 ms, p95 18.5-21 ms, GPU 14 ms; late frames held two vsyncs (73 times) |
| V4 frame step, 30 fps | Mac, 720p, 55 s | No crash. Frame p50 33.3 ms, p95 34-36 ms; 10 frames held three vsyncs around loading |


## Known issues and open work

- **V4, V5 and V6 are not yet tested on the iPhone.**
- **The busy game thread (fixed in V7):** `OptimizeChangeBanc` (a `sead::Thread` whose work function, `main+0xf7a0`, sleeps 16 ms only when everything is loaded) used a whole core because the 2.38 GB alias region ran out: the streaming allocator stops at +2.26 GB where it wants +4.5-4.75 GB, and the loader retries. Same host, Mac: 2.38 GB → 997-998 ms/s in 20 of 20 windows, process CPU 308%; 8 GB → asleep, about 168%. With a damaged dump, #1530's substitute is the other fix.
- **The iPhone's address space:** since V7 the profile reserves 17.6 GB (8 GB alias region). The iPhone 18 Pro already took a 12 GB reservation plus 12 GB of guest files, but the larger one is not yet confirmed on a phone. If the app stops at start, `DM_ALIAS_SIZE=0x98000000` in its `Documents/env.txt` goes back to the small region.
- **iPhone heat:** at thermal state "serious" iOS moves the game to its efficiency cores (V6: fast-core share 55% → 19%, CPU per frame 5.5 → 11.8 ms) while the GPU stays at 12-14 ms. Start cool and not charging; for long sessions, Frame rate 30.
- **Build order:** an iPhone build and a Mac build share the shader cache; after an iPhone build, run the Mac build again (`--platform mac`, about 10 minutes from the cache) before playing on the Mac, and never run the game while a build is running, and the 30 fps game speed is not yet measured (see [Frame rate](#frame-rate)).
- **iPhone frame rate:** V2 ran at about 38 fps after the opening cutscene. The GPU needs 15-22 ms a frame at 720p, at or over the 16.7 ms of 60 fps, and iOS moved the game onto the efficiency cores as the run went on (about 1.5 GHz). Run inside LiveContainer, the app's own Game Mode and games category (`LSSupportsGameMode`, `LSApplicationCategoryType`) probably do not apply; a direct install, a cool phone and the Performance HUD off are the next things to measure. V3 reached about 40 fps at best. V4's 30 fps setting gives a steady alternative.
- **Mac frame rate:** mostly 60 fps at 720p on the MacBook Air M5, with dips outdoors (GPU 13-19 ms a frame), more when the Mac is hot. Without the 720p file the game renders up to 1440 × 810 and Kokiri Forest runs at 43-52 fps.
- **Two stalls of about 0.9 s** in a Mac play test, on the game's side (the submit time was small). Not investigated.
- **Texture release level 2:** if the game read back a released texture on the CPU, it would read zeros. Not seen in testing.
- **One shader fails to translate** (of 42,854); whether the game uses it is unknown.
- **Memory** can still climb to about 10 GB on some area changes with guest memory in RAM.
- **No app icon**, and no offline pipeline archive in the IPA: the first start on the iPhone prepares about 30,500 pipelines (it may take 20-40 minutes), once. An archive made on the Mac needs the iPhone 18 Pro's GPU architecture name, which its log prints (`none for this GPU (applegpu_…)`).
- **Upstream PRs not merged:** #1427, #1405, #1453 and the frame-pacing parts of #1444.
- **Not checked:** areas past Kokiri Forest and its surroundings on the iPhone; the Mac app's docked mode at length.

## Credits

The upstream nxnative project and its contributors, the authors of the Ocarina of Time branch and the pull requests above, and the projects nxnative is built on ([Acknowledgements](../../README.md#acknowledgements)). This fork is not affiliated with Nintendo.
