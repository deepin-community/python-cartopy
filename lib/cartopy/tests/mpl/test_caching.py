# Copyright Cartopy Contributors
#
# This file is part of Cartopy and is released under the LGPL license.
# See COPYING and COPYING.LESSER in the root of the repository for full
# licensing details.

import gc

try:
    from owslib.wmts import WebMapTileService
except ImportError:
    WebMapTileService = None
import matplotlib.pyplot as plt
import numpy as np
import pytest

import cartopy.crs as ccrs
from cartopy.mpl.feature_artist import FeatureArtist
from cartopy.io.ogc_clients import WMTSRasterSource, _OWSLIB_AVAILABLE
import cartopy.io.shapereader
import cartopy.mpl.geoaxes as cgeoaxes
import cartopy.mpl.patch
from cartopy.tests.mpl import ImageTesting


def sample_data(shape=(73, 145)):
    """Return ``lons``, ``lats`` and ``data`` of some fake data."""
    nlats, nlons = shape
    lats = np.linspace(-np.pi / 2, np.pi / 2, nlats)
    lons = np.linspace(0, 2 * np.pi, nlons)
    lons, lats = np.meshgrid(lons, lats)
    wave = 0.75 * (np.sin(2 * lats) ** 8) * np.cos(4 * lons)
    mean = 0.5 * np.cos(2 * lats) * ((np.sin(2 * lats)) ** 2 + 2)

    lats = np.rad2deg(lats)
    lons = np.rad2deg(lons)
    data = wave + mean

    return lons, lats, data


class CallCounter:
    """
    Exposes a context manager which can count the number of calls to a specific
    function. (useful for cache checking!)

    Internally, the target function is replaced with a new one created
    by this context manager which then increments ``self.count`` every
    time it is called.

    Example usage::

        show_counter = CallCounter(plt, 'show')
        with show_counter:
            plt.show()
            plt.show()
            plt.show()

        print show_counter.count    # <--- outputs 3


    """
    def __init__(self, parent, function_name):
        self.count = 0
        self.parent = parent
        self.function_name = function_name
        self.orig_fn = getattr(parent, function_name)

    def __enter__(self):
        def replacement_fn(*args, **kwargs):
            self.count += 1
            return self.orig_fn(*args, **kwargs)

        setattr(self.parent, self.function_name, replacement_fn)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        setattr(self.parent, self.function_name, self.orig_fn)


@pytest.mark.natural_earth
def test_coastline_loading_cache():
    # a5caae040ee11e72a62a53100fe5edc355304419 added coastline caching.
    # This test ensures it is working.

    # Create coastlines to ensure they are cached.
    ax1 = plt.subplot(2, 1, 1, projection=ccrs.PlateCarree())
    ax1.coastlines()
    plt.draw()
    # Create another instance of the coastlines and count
    # the number of times shapereader.Reader is created.
    counter = CallCounter(cartopy.io.shapereader.Reader, '__init__')
    with counter:
        ax2 = plt.subplot(2, 1, 1, projection=ccrs.Robinson())
        ax2.coastlines()
        plt.draw()

    assert counter.count == 0, (
        f'The shapereader Reader class was created {counter.count} times, '
        f'indicating that the caching is not working.')

    plt.close()


# Use an empty ImageTesting decorator to force the switch to
# the Agg backend (fails on macosx without it)
@pytest.mark.natural_earth
@ImageTesting([])
def test_shapefile_transform_cache():
    # a5caae040ee11e72a62a53100fe5edc355304419 added shapefile mpl
    # geometry caching based on geometry object id. This test ensures
    # it is working.
    coastline_path = cartopy.io.shapereader.natural_earth(resolution="110m",
                                                          category='physical',
                                                          name='coastline')
    geoms = cartopy.io.shapereader.Reader(coastline_path).geometries()
    # Use the first 10 of them.
    geoms = tuple(geoms)[:10]
    n_geom = len(geoms)

    ax = plt.axes(projection=ccrs.Robinson())

    # Empty the cache.
    FeatureArtist._geom_key_to_geometry_cache.clear()
    FeatureArtist._geom_key_to_path_cache.clear()
    assert len(FeatureArtist._geom_key_to_geometry_cache) == 0
    assert len(FeatureArtist._geom_key_to_path_cache) == 0

    counter = CallCounter(ax.projection, 'project_geometry')
    with counter:
        ax.add_geometries(geoms, ccrs.PlateCarree())
        ax.add_geometries(geoms, ccrs.PlateCarree())
        ax.add_geometries(geoms[:], ccrs.PlateCarree())
        ax.figure.canvas.draw()

    # Without caching the count would have been
    # n_calls * n_geom, but should now be just n_geom.
    assert counter.count == n_geom, (
        f'The given geometry was transformed too many times (expected: '
        f'{n_geom}; got {counter.count}) - the caching is not working.')

    # Check the cache has an entry for each geometry.
    assert len(FeatureArtist._geom_key_to_geometry_cache) == n_geom
    assert len(FeatureArtist._geom_key_to_path_cache) == n_geom

    # Check that the cache is empty again once we've dropped all references
    # to the source paths.
    plt.clf()
    del geoms
    gc.collect()
    assert len(FeatureArtist._geom_key_to_geometry_cache) == 0
    assert len(FeatureArtist._geom_key_to_path_cache) == 0

    plt.close()


def test_contourf_transform_path_counting():
    fig = plt.figure()
    ax = plt.axes(projection=ccrs.Robinson())
    fig.canvas.draw()

    # Capture the size of the cache before our test.
    gc.collect()
    initial_cache_size = len(cgeoaxes._PATH_TRANSFORM_CACHE)

    path_to_geos_counter = CallCounter(cartopy.mpl.patch, 'path_to_geos')
    with path_to_geos_counter:
        x, y, z = sample_data((30, 60))
        cs = plt.contourf(x, y, z, 5, transform=ccrs.PlateCarree())
        n_geom = sum([len(c.get_paths()) for c in cs.collections])
        del cs
        ax.figure.canvas.draw()

    # Before the performance enhancement, the count would have been 2 * n_geom,
    # but should now be just n_geom.
    assert path_to_geos_counter.count == n_geom, (
        f'The given geometry was transformed too many times (expected: '
        f'{n_geom}; got {path_to_geos_counter.count}) - the caching is not '
        f'working.')

    # Check the cache has an entry for each geometry.
    assert len(cgeoaxes._PATH_TRANSFORM_CACHE) == initial_cache_size + n_geom

    # Check that the cache is empty again once we've dropped all references
    # to the source paths.
    plt.clf()
    gc.collect()
    assert len(cgeoaxes._PATH_TRANSFORM_CACHE) == initial_cache_size

    plt.close()


@pytest.mark.filterwarnings("ignore:TileMatrixLimits")
@pytest.mark.network
@pytest.mark.skipif(not _OWSLIB_AVAILABLE, reason='OWSLib is unavailable.')
@pytest.mark.xfail(raises=KeyError, reason='OWSLib WMTS support is broken.')
def test_wmts_tile_caching():
    image_cache = WMTSRasterSource._shared_image_cache
    image_cache.clear()
    assert len(image_cache) == 0

    url = 'https://map1c.vis.earthdata.nasa.gov/wmts-geo/wmts.cgi'
    wmts = WebMapTileService(url)
    layer_name = 'MODIS_Terra_CorrectedReflectance_TrueColor'

    source = WMTSRasterSource(wmts, layer_name)

    gettile_counter = CallCounter(wmts, 'gettile')
    crs = ccrs.PlateCarree()
    extent = (-180, 180, -90, 90)
    resolution = (20, 10)
    with gettile_counter:
        source.fetch_raster(crs, extent, resolution)
    n_tiles = 2
    assert gettile_counter.count == n_tiles, (
        f'Too many tile requests - expected {n_tiles}, got '
        f'{gettile_counter.count}.')
    gc.collect()
    assert len(image_cache) == 1
    assert len(image_cache[wmts]) == 1
    tiles_key = (layer_name, '0')
    assert len(image_cache[wmts][tiles_key]) == n_tiles

    # Second time around we shouldn't request any more tiles so the
    # call count will stay the same.
    with gettile_counter:
        source.fetch_raster(crs, extent, resolution)
    assert gettile_counter.count == n_tiles, (
        f'Too many tile requests - expected {n_tiles}, got '
        f'{gettile_counter.count}.')
    gc.collect()
    assert len(image_cache) == 1
    assert len(image_cache[wmts]) == 1
    tiles_key = (layer_name, '0')
    assert len(image_cache[wmts][tiles_key]) == n_tiles

    # Once there are no live references the weak-ref cache should clear.
    del source, wmts, gettile_counter
    gc.collect()
    assert len(image_cache) == 0
