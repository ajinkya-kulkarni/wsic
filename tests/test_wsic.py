#!/usr/bin/env python

"""Tests for `wsic` package."""
import sys
from pathlib import Path

import numpy as np
import pytest
import tifffile
from click.testing import CliRunner

from wsic import cli, readers, writers


@pytest.fixture()
def samples_path():
    """Return the path to the samples."""
    return Path(__file__).parent / "samples"


def test_jp2_to_deflate_tiled_tiff(samples_path, tmp_path):
    """Test that we can convert a JP2 to a DEFLATE compressed tiled TIFF."""
    reader = readers.Reader.from_file(samples_path / "XYC.jp2")
    writer = writers.TIFFWriter(
        path=tmp_path / "XYC.tiff",
        shape=reader.shape,
        overwrite=False,
        tile_size=(256, 256),
        compression="deflate",
        compression_level=70,
    )
    writer.copy_from_reader(reader=reader, num_workers=3, read_tile_size=(512, 512))
    assert writer.path.exists()
    assert writer.path.is_file()
    assert writer.path.stat().st_size > 0
    output = tifffile.imread(writer.path)
    assert np.all(reader[:512, :512] == output[:512, :512])


def test_jp2_to_deflate_pyramid_tiff(samples_path, tmp_path):
    """Test that we can convert a JP2 to a DEFLATE compressed pyramid TIFF."""
    reader = readers.Reader.from_file(samples_path / "XYC.jp2")
    pyramid_downsamples = [2, 4]
    writer = writers.TIFFWriter(
        path=tmp_path / "XYC.tiff",
        shape=reader.shape,
        overwrite=False,
        tile_size=(256, 256),
        compression="deflate",
        pyramid_downsamples=pyramid_downsamples,
    )
    writer.copy_from_reader(reader=reader, num_workers=3, read_tile_size=(512, 512))
    assert writer.path.exists()
    assert writer.path.is_file()
    assert writer.path.stat().st_size > 0
    output = tifffile.imread(writer.path)
    assert np.all(reader[:512, :512] == output[:512, :512])
    tif = tifffile.TiffFile(writer.path)
    assert len(tif.series[0].levels) == len(pyramid_downsamples) + 1


def test_pyramid_tiff_no_cv2(samples_path, tmp_path, monkeypatch):
    """Test pyramid generation when cv2 is not installed."""
    # Make cv2 unavailable
    monkeypatch.setitem(sys.modules, "cv2", None)
    # Sanity check the import fails
    with pytest.raises(ImportError):
        import cv2  # noqa
    # Try to make a pyramid TIFF
    reader = readers.Reader.from_file(samples_path / "XYC.jp2")
    pyramid_downsamples = [2, 4]
    writer = writers.TIFFWriter(
        path=tmp_path / "XYC.tiff",
        shape=reader.shape,
        overwrite=False,
        tile_size=(256, 256),
        compression="deflate",
        pyramid_downsamples=pyramid_downsamples,
    )
    writer.copy_from_reader(reader=reader, num_workers=3, read_tile_size=(512, 512))
    assert writer.path.exists()
    assert writer.path.is_file()
    assert writer.path.stat().st_size > 0
    output = tifffile.imread(writer.path)
    assert np.all(reader[:512, :512] == output[:512, :512])
    tif = tifffile.TiffFile(writer.path)
    assert len(tif.series[0].levels) == len(pyramid_downsamples) + 1


def test_pyramid_tiff_no_cv2_no_scipy(samples_path, tmp_path, monkeypatch):
    """Test pyramid generation when neither cv2 or scipy are installed."""
    # Make cv2 and scipy unavailable
    monkeypatch.setitem(sys.modules, "cv2", None)
    monkeypatch.setitem(sys.modules, "scipy", None)
    # Sanity check the imports fail
    with pytest.raises(ImportError):
        import cv2  # noqa
    with pytest.raises(ImportError):
        import scipy  # noqa
    # Try to make a pyramid TIFF
    reader = readers.Reader.from_file(samples_path / "XYC.jp2")
    pyramid_downsamples = [2, 4]
    writer = writers.TIFFWriter(
        path=tmp_path / "XYC.tiff",
        shape=reader.shape,
        overwrite=False,
        tile_size=(256, 256),
        compression="deflate",
        pyramid_downsamples=pyramid_downsamples,
    )
    writer.copy_from_reader(reader=reader, num_workers=3, read_tile_size=(512, 512))
    assert writer.path.exists()
    assert writer.path.is_file()
    assert writer.path.stat().st_size > 0
    output = tifffile.imread(writer.path)
    assert np.all(reader[:512, :512] == output[:512, :512])
    tif = tifffile.TiffFile(writer.path)
    assert len(tif.series[0].levels) == len(pyramid_downsamples) + 1


def test_jp2_to_webp_tiled_tiff(samples_path, tmp_path):
    """Test that we can convert a JP2 to a WebP compressed tiled TIFF."""
    reader = readers.Reader.from_file(samples_path / "XYC.jp2")
    writer = writers.TIFFWriter(
        path=tmp_path / "XYC.tiff",
        shape=reader.shape,
        overwrite=False,
        tile_size=(256, 256),
        compression="WebP",
        compression_level=70,
    )
    writer.copy_from_reader(reader=reader, num_workers=3, read_tile_size=(512, 512))
    assert writer.path.exists()
    assert writer.path.is_file()
    assert writer.path.stat().st_size > 0
    output = tifffile.imread(writer.path)
    assert np.all(reader[:512, :512] == output[:512, :512])


def test_cli_jp2_to_tiff(samples_path, tmp_path):
    """Test the CLI."""
    runner = CliRunner()
    with runner.isolated_filesystem(temp_dir=tmp_path) as td:
        in_path = str(samples_path / "XYC.jp2")
        out_path = str(Path(td) / "XYC.tiff")
        result = runner.invoke(
            cli.convert,
            ["-i", in_path, "-o", out_path],
            catch_exceptions=False,
        )
    assert result.exit_code == 0


def test_help():
    """Test the help output."""
    runner = CliRunner()
    help_result = runner.invoke(cli.main, ["--help"])
    assert help_result.exit_code == 0
    assert "Console script for wsic." in help_result.output
