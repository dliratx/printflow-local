# Third-party components

PrintFlow's own source is MIT licensed. Dependencies retain their original
licenses; a container is not a relicensing mechanism.

| Component | Source / version | License / role |
| --- | --- | --- |
| Native U1 MCP base | `JSCodesTech/snapmaker_u1_mcp` at `45240299c46c7ceee8725a0ffecadd89a2b5bcc4` | MIT, vendored license retained |
| CadQuery | 2.8.0, https://github.com/CadQuery/cadquery | Apache 2.0, parametric CAD |
| trimesh | 4.4.9, https://github.com/mikedh/trimesh | MIT, mesh topology checks and degenerate triangle cleanup |
| Manifold | 3.3.2, https://github.com/elalish/manifold | Apache 2.0, capped solid partitioning |
| Pillow | 13.0.0, https://github.com/python-pillow/Pillow | MIT-CMU, photo validation and metadata-free image conversion |
| NumPy | 2.5.4, https://github.com/numpy/numpy | BSD-3-Clause; wheel notices also include 0BSD, MIT, Zlib and CC0-1.0 components. Vectorized full-mesh preview buffers. |
| Original 3DBenchy | Daniel NorÃ©e / Creative Tools, https://www.3dbenchy.com/download/ | CC0 1.0 per the current official license page; benchmark asset |
| Open CASCADE / OCP | `cadquery-ocp` 7.9.3.1.1 | OCCT LGPL 2.1 with exception; review bundled notices |
| TripoSR source | https://github.com/VAST-AI-Research/TripoSR at `107cefdc244c39106fa830359024f6a2f1c78871` | MIT, with retained notices for derived Apache code |
| TripoSR weights | https://huggingface.co/stabilityai/TripoSR at `5b521936b01fbe1890f6f9baed0254ab6351c04a` | MIT, local image reconstruction |
| U2Net | https://github.com/xuebinqin/U-2-Net; pinned `u2net.onnx` distributed by rembg | Apache 2.0, local foreground segmentation; provenance/checksum and license retained with weights |
| ONNX Runtime | 1.23.2, https://github.com/microsoft/onnxruntime | MIT, CPU foreground inference |
| DINO configuration | `facebook/dino-vitb16` at `f205d5d8e640a89a2b8ef0369670dfc37cc07fc2` | Encoder architecture config only; effective weights are in TripoSR |
| scikit-image | 0.24.0 | BSD, portable CPU mesh extraction |
| PyTorch CPU | 2.9.1 | BSD-style, local inference |
| ROCm PyTorch image | `rocm7.2_ubuntu24.04_py3.12_pytorch_release_2.9.1` | Upstream component licenses, optional AMD runtime |

The TripoSR wrapper replaces its CUDA-oriented marching-cubes extension with
scikit-image, keeps the density grid's XYZ axes, loads the pinned DINO config
offline, and makes the unused background-removal import optional. Source and
weight provenance is recorded by the bootstrap script. No gated model login
or paid Meshy account is required.

TripoSR model SHA-256:
`429e2c6b22a0923967459de24d67f05962b235f79cde6b032aa7ed2ffcd970ee`.

The current Codex/ChatGPT account integration uses an external service with its
own terms. Windows and the installed GPU driver also retain their own licenses.
The app's provider/worker boundary allows additional engines without changing
the printer adapter or library. No fully local language-model chat provider is
implemented in this release.

The bundled unmodified `models/calibration-assets/3DBenchy.stl` has SHA-256
`6ab57f1c3f8e86bc3cbd302c6fa6270acf06277c6335454e922419c25d42e97e`.
Its download and license sources are retained in `source.json` beside the asset.
The [current official license](https://www.3dbenchy.com/license/) was checked on
October 27, 2026. Keep the original scale and geometry when comparing benchmarks.

The documentation's image-to-3D screenshot displays the unmodified TripoSR
`examples/teapot.png` reference at the source revision pinned above. Its SHA-256
is `66b0b8f7dd759e97d20665999885e0548f96c95dadee6bf9762ccd877c596b8c`.
The upstream MIT notice is retained in `docs/screenshots/TripoSR-LICENSE.txt`.
See [screenshot provenance](docs/SCREENSHOTS.md#capture-and-attribution-notes).
