import multiprocessing
import os
import time
import warnings
from abc import ABC
from pathlib import Path
from typing import Iterator, Optional, Tuple, Union

import numpy as np

from wsic.magic import summon_file_types
from wsic.types import PathLike


class Reader(ABC):
    """Base class for readers."""

    def __init__(self, path: PathLike):
        """Initialize reader.

        Args:
            path (PathLike):
                Path to file.
        """
        self.path = Path(path)

    def __getitem__(index: Tuple[Union[int, slice], ...]) -> np.ndarray:
        """Get pixel data at index."""
        raise NotImplementedError

    @classmethod
    def from_file(cls, path: Path) -> "Reader":
        """Return reader for file.

        Args:
            path (Path): Path to file.

        Returns:
            Reader: Reader for file.
        """
        file_types = summon_file_types(path)
        if ("jp2",) in file_types:
            return JP2Reader(path)
        if ("tiff", "svs") in file_types:
            return OpenSlideReader(path)
        if ("tiff",) in file_types:
            return TIFFReader(path)
        raise ValueError(f"Unsupported file type: {path}")


def get_tile(
    queue: multiprocessing.Queue,
    ji: Tuple[int, int],
    tilesize: Tuple[int, int],
    path: Path,
) -> np.ndarray:
    """Append a tile read from a reader to a multiprocessing queue.

    Args:
        queue (multiprocessing.Queue):
            Queue to put tiles on to.
        ji (Tuple[int, int]):
            Index of tile.
        tilesize (Tuple[int, int]):
            Tile size as (width, height).
        path (Path):
            Path to file to read from.

    Returns:
        Tuple[Tuple[int, int], np.ndarray]:
            Tuple of the tile index and the tile.
    """
    reader = Reader.from_file(path)
    # Read the tile
    j, i = ji
    index = (
        slice(j * tilesize[1], (j + 1) * tilesize[1]),
        slice(i * tilesize[0], (i + 1) * tilesize[0]),
    )
    # Filter warnings (e.g. from gylmur about reading past the edge)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tile = reader[index]
    queue.put((ji, tile))


class MultiProcessTileIterator:
    """An iterator which returns tiles generated by a reader.

    This is a fancy iterator that uses a multiprocress queue to
    accelerate the reading of tiles. It can also use an intermediate
    file to allow for reading and writing with different tile sizes.

    Args:
        reader (Reader):
            Reader for image.
        read_tile_size (Tuple[int, int]):
            Tile size to read from reader.
        yield_tile_size (Optional[Tuple[int, int]]):
            Tile size to yield. If None, yield_tile_size = read_tile_size.
        num_workers (int):
            Number of workers to use.
        intermediate (Path):
            Intermediate reader/writer to use. Must support random
            access reads and writes.
        verbose (bool):
            Verbose output.

    Yields:
        np.ndarray:
            A tile from the reader.
    """

    def __init__(
        self,
        reader: Reader,
        read_tile_size: Tuple[int, int],
        yield_tile_size: Optional[Tuple[int, int]] = None,
        num_workers: int = None,
        intermediate=None,
        verbose: bool = False,
    ) -> None:

        self.reader = reader
        self.shape = reader.shape
        self.read_tile_size = read_tile_size
        self.yield_tile_size = yield_tile_size or read_tile_size
        self.intermediate = intermediate
        self.verbose = verbose
        self.queue = multiprocessing.Queue()
        self.enqueued = set()
        self.reordering_dict = {}
        self.read_j = 0
        self.read_i = 0
        self.yield_i = 0
        self.yield_j = 0
        self.num_workers = num_workers or os.cpu_count() or 2
        self.read_tiles_shape = (
            int(np.ceil(self.shape[0] / self.read_tile_size[1])),
            int(np.ceil(self.shape[1] / self.read_tile_size[0])),
        )
        self.yield_tile_shape = (
            int(np.ceil(self.shape[0] / self.yield_tile_size[1])),
            int(np.ceil(self.shape[1] / self.yield_tile_size[0])),
        )
        self.remaining_reads = list(np.ndindex(self.read_tiles_shape))

        # Validation and error handling
        if self.read_tile_size != self.yield_tile_size and not self.intermediate:
            raise ValueError(
                f"read_tile_size ({self.read_tile_size})"
                f" != yield_tile_size ({self.yield_tile_size})"
                " and intermediate is not set. An intermediate is required when the read"
                " and yield tile size differ."
            )

    def __len__(self) -> int:
        """Return the number of tiles in the reader."""
        return int(np.prod(self.yield_tile_shape))

    def __iter__(self) -> Iterator:
        """Return an iterator for the reader."""
        self.read_j = 0
        self.read_i = 0
        return self

    def __next__(self) -> np.ndarray:
        """Return the next tile from the reader."""
        # Increment the read ij index
        if self.read_i >= self.read_tiles_shape[1]:
            self.read_i = 0
            self.read_j += 1
        if self.read_j >= self.read_tiles_shape[0]:
            if self.verbose:
                print(f"Read all tiles")

        # Increment the yield ij index
        if self.yield_i >= self.yield_tile_shape[1]:
            self.yield_i = 0
            self.yield_j += 1
        if self.yield_j >= self.yield_tile_shape[0]:
            raise StopIteration

        # Add tile reads to the queue until the maximum number of workers is reached
        self.fill_queue()

        # Get the next yield tile from the queue
        while True:
            # Remove all tiles from the queue into the reordering dict
            self.empty_queue()

            # Remove the next tile from the reordering dict
            if (self.read_j, self.read_i) in self.reordering_dict:
                self.enqueued.remove((self.read_j, self.read_i))
                tile = self.reordering_dict.pop((self.read_j, self.read_i))

                # If no intermediate is required, return the tile
                if not self.intermediate:
                    self.read_i += 1
                    self.yield_i += 1
                    return tile

                # Otherwise, write the tile to the intermediate
                intermediate_write_index = (
                    slice(
                        self.read_j * self.read_tile_size[1],
                        self.read_j * self.read_tile_size[1] + tile.shape[0],
                    ),
                    slice(
                        self.read_i * self.read_tile_size[0],
                        self.read_i * self.read_tile_size[0] + tile.shape[1],
                    ),
                )
                self.intermediate[intermediate_write_index] = tile
                self.read_i += 1

            # Return the next tile from the intermediate
            if self.intermediate:
                intermediate_read_index = (
                    slice(
                        self.yield_j * self.yield_tile_size[1],
                        (self.yield_j + 1) * self.yield_tile_size[1],
                    ),
                    slice(
                        self.yield_i * self.yield_tile_size[0],
                        (self.yield_i + 1) * self.yield_tile_size[0],
                    ),
                )
                tile = self.intermediate[intermediate_read_index]
                if np.count_nonzero(tile) > 0:
                    self.yield_i += 1
                    return tile

            # Ensure the queue is kept full
            self.fill_queue()

            # Sleep and try again
            time.sleep(0.1)

    def empty_queue(self) -> None:
        """Remove all tiles from the queue into the reordering dict."""
        while not self.queue.empty():
            ji, tile = self.queue.get()
            self.reordering_dict[ji] = tile

    def fill_queue(self) -> None:
        """Add tile reads to the queue until the maximum number of workers is reached."""
        while len(self.enqueued) < self.num_workers and len(self.remaining_reads) > 0:
            next_ji = self.remaining_reads.pop(0)
            proc = multiprocessing.Process(
                target=get_tile,
                args=(
                    self.queue,
                    next_ji,
                    self.read_tile_size,
                    self.reader.path,
                ),
            )
            proc.start()
            self.enqueued.add(next_ji)


class JP2Reader(Reader):
    """Reader for JP2 files using glymur.

    Args:
        path (Path): Path to file.
    """

    def __init__(self, path: Path) -> None:
        super().__init__(path)
        import glymur

        if glymur.options.version.openjpeg_version_tuple >= (2, 2, 0):
            glymur.set_option("lib.num_threads", multiprocessing.cpu_count())
        self.jp2 = glymur.Jp2k(str(path))
        self.shape = self.jp2.shape
        self.dtype = np.uint8
        self.axes = "YXS"

    def __getitem__(self, index: tuple) -> np.ndarray:
        """Get pixel data at index."""
        return self.jp2[index]


class TIFFReader(Reader):
    """Reader for TIFF files using tifffile."""

    def __init__(self, path: Path) -> None:
        """Initialize reader.

        Args:
            path (Path): Path to file.
        """
        import tifffile

        super().__init__(path)
        self.tiff = tifffile.TiffFile(str(path))
        self.array = self.tiff.pages[0].asarray()
        self.shape = self.array.shape
        self.dtype = self.array.dtype
        self.axes = self.tiff.series[0].axes

    def __getitem__(self, index: Tuple[Union[slice, int]]) -> np.ndarray:
        """Get pixel data at index."""
        return self.array[index]


class OpenSlideReader(Reader):
    """Reader for OpenSlide files using openslide-python."""

    def __init__(self, path: Path) -> None:
        import openslide

        super().__init__(path)
        self.os_slide = openslide.OpenSlide(str(path))
        self.shape = self.os_slide.level_dimensions[0][::-1] + (3,)
        self.dtype = np.uint8

    def __getitem__(self, index: Tuple[Union[int, slice], ...]) -> np.ndarray:
        """Get pixel data at index."""
        xs: slice = index[1]
        ys: slice = index[0]
        start_x = xs.start or 0
        start_y = ys.start or 0
        end_x = xs.stop or self.shape[1]
        end_y = ys.stop or self.shape[0]

        # Prevent reading past the edges of the image
        end_x = min(end_x, self.shape[1])
        end_y = min(end_y, self.shape[0])

        # Read the image
        img = self.os_slide.read_region(
            location=(start_x, start_y),
            level=0,
            size=(end_x - start_x, end_y - start_y),
        )
        return np.array(img.convert("RGB"))
