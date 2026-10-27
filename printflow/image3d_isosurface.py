"""Portable isosurface extraction: skimage keeps the volume's XYZ axis order."""
import numpy as np
import torch
from skimage.measure import marching_cubes


class MarchingCubeHelper(torch.nn.Module):
    points_range = (0, 1)

    def __init__(self, resolution):
        super().__init__()
        self.resolution = resolution
        self._grid_vertices = None

    @property
    def grid_vertices(self):
        if self._grid_vertices is None:
            axes = [torch.linspace(0, 1, self.resolution) for _ in range(3)]
            self._grid_vertices = torch.stack(torch.meshgrid(*axes, indexing="ij"), dim=-1).reshape(-1, 3)
        return self._grid_vertices

    def forward(self, level):
        volume = -level.detach().float().cpu().numpy().reshape((self.resolution,) * 3)
        vertices, faces, _, _ = marching_cubes(volume, level=0, allow_degenerate=False)
        # Unlike torchmcubes, skimage already returns indices in volume-axis order.
        vertices = np.ascontiguousarray(vertices / (self.resolution - 1))
        faces = np.ascontiguousarray(faces.astype(np.int64))
        return torch.from_numpy(vertices).to(level.device), torch.from_numpy(faces).to(level.device)
