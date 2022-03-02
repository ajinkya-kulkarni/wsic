"""Console script for wsic."""
import sys
from pathlib import Path
from typing import Tuple

import click

import wsic

ext2writer = {
    ".jp2": wsic.writers.JP2Writer,
    ".tiff": wsic.writers.TiledTIFFWriter,
    ".zarr": wsic.writers.ZarrReaderWriter,
}


@click.group(context_settings={"help_option_names": ["-h", "--help"]})
@click.option("--debug/--no-debug", default=False)
@click.pass_context
def main(ctx, debug):
    """Console script for wsic."""
    ctx.ensure_object(dict)
    ctx.obj["DEBUG"] = debug


@main.command()
# @click.pass_context
@click.option(
    "-i",
    "--in-path",
    help="Path to WSI to read from.",
    type=click.Path(exists=True),
)
@click.option(
    "-o",
    "--out-path",
    help="The path to output to.",
    type=click.Path(),
)
@click.option(
    "-t",
    "--tile-size",
    help="The size of the tiles to write.",
    type=click.Tuple([int, int]),
    default=(256, 256),
)
@click.option(
    "-r",
    "--read-tile-size",
    help="The size of the tiles to read.",
    type=click.Tuple([int, int]),
    default=(512, 512),
)
@click.option(
    "-w",
    "--workers",
    help="The number of workers to use.",
    type=int,
    default=3,
)
@click.option(
    "--compression",
    help="The compression to use.",
    type=click.Choice(["deflate", "webp", "jpeg", "jpeg2000"]),
    default="deflate",
)
@click.option(
    "--compression-level",
    help="The compression level to use.",
    type=int,
    default=0,
)
@click.option(
    "--overwrite/--no-overwrite",
    help="Whether to overwrite the output file.",
    default=False,
)
def convert(
    in_path: str,
    out_path: str,
    tile_size: Tuple[int, int],
    read_tile_size: Tuple[int, int],
    workers: int,
    compression: str,
    compression_level: int,
    overwrite: bool,
):
    """Convert a WSI."""
    in_path = Path(in_path)
    out_path = Path(out_path)
    reader = wsic.readers.Reader.from_file(in_path)
    writer_cls = ext2writer[out_path.suffix]
    writer = writer_cls(
        out_path,
        shape=reader.shape,
        tile_size=tile_size,
        compression=compression,
        compression_level=compression_level,
        overwrite=overwrite,
    )
    writer.copy_from_reader(reader, read_tile_size=read_tile_size, num_workers=workers)


if __name__ == "__main__":
    sys.exit(main())  # pragma: no cover
