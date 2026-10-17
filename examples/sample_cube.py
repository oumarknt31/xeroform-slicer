"""Minimal example: make a cube, slice it, write a .cli file."""
import trimesh

from slicerkit import slice_file, SliceConfig

trimesh.creation.box(extents=[20, 20, 20]).export("cube.stl")

layers = slice_file(
    "cube.stl",
    "cube.cli",
    SliceConfig(layer_thickness=0.5, hatch_distance=0.5),
)
print(f"sliced {len(layers)} layers -> cube.cli")
