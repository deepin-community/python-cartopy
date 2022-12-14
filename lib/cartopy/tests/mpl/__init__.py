# Copyright Cartopy Contributors
#
# This file is part of Cartopy and is released under the LGPL license.
# See COPYING and COPYING.LESSER in the root of the repository for full
# licensing details.

import base64
import os
import glob
import shutil
import warnings

import flufl.lock
import matplotlib as mpl
import matplotlib.pyplot as plt
import matplotlib.patches as mpatches
from matplotlib.testing import setup as mpl_setup
import matplotlib.testing.compare as mcompare
import packaging.version


MPL_VERSION = packaging.version.parse(mpl.__version__)


class ImageTesting:
    """
    Provides a convenient class for running visual Matplotlib tests.

    In general, this class should be used as a decorator to a test function
    which generates one (or more) figures.

    ::

        @ImageTesting(['simple_test'])
        def test_simple():

            import matplotlib.pyplot as plt
            plt.plot(range(10))


    To find out where the result and expected images reside one can create
    a empty ImageTesting class instance and get the paths from the
    :meth:`expected_path` and :meth:`result_path` methods::

        >>> import os
        >>> import cartopy.tests.mpl
        >>> img_testing = cartopy.tests.mpl.ImageTesting([])
        >>> exp_fname = img_testing.expected_path('<TESTNAME>', '<IMGNAME>')
        >>> result_fname = img_testing.result_path('<TESTNAME>', '<IMGNAME>')
        >>> img_test_mod_dir = os.path.dirname(cartopy.__file__)

        >>> print('Result:', os.path.relpath(result_fname, img_test_mod_dir))
        ... # doctest: +ELLIPSIS
        Result: ...output/<TESTNAME>/result-<IMGNAME>.png

        >>> print('Expected:', os.path.relpath(exp_fname, img_test_mod_dir))
        Expected: tests/mpl/baseline_images/mpl/<TESTNAME>/<IMGNAME>.png

    .. note::

        Subclasses of the ImageTesting class may decide to change the
        location of the expected and result images. However, the same
        technique for finding the locations of the images should hold true.

    """

    #: The path where the standard ``baseline_images`` exist.
    root_image_results = os.path.dirname(__file__)

    #: The path where the images generated by the tests should go.
    image_output_directory = os.path.join(root_image_results, 'output')
    if not os.access(image_output_directory, os.W_OK):
        if not os.access(os.getcwd(), os.W_OK):
            raise OSError('Write access to a local disk is required to run '
                          'image tests.  Run the tests from a current working '
                          'directory you have write access to to avoid this '
                          'issue.')
        else:
            image_output_directory = os.path.join(os.getcwd(),
                                                  'cartopy_test_output')

    def __init__(self, img_names, tolerance=0.5, style='classic'):
        # With matplotlib v1.3 the tolerance keyword is an RMS of the pixel
        # differences, as computed by matplotlib.testing.compare.calculate_rms
        self.img_names = img_names
        self.style = style
        self.tolerance = tolerance

    def expected_path(self, test_name, img_name, ext='.png'):
        """
        Return the full path (minus extension) of where the expected image
        should be found, given the name of the image being tested and the
        name of the test being run.

        """
        expected_fname = os.path.join(self.root_image_results,
                                      'baseline_images', 'mpl', test_name,
                                      img_name)
        return expected_fname + ext

    def result_path(self, test_name, img_name, ext='.png'):
        """
        Return the full path (minus extension) of where the result image
        should be given the name of the image being tested and the
        name of the test being run.

        """
        result_fname = os.path.join(self.image_output_directory,
                                    test_name, 'result-' + img_name)
        return result_fname + ext

    def run_figure_comparisons(self, figures, test_name):
        """
        Run the figure comparisons against the ``image_names``.

        The number of figures passed must be equal to the number of
        image names in ``self.image_names``.

        .. note::

            The figures are not closed by this method. If using the decorator
            version of ImageTesting, they will be closed for you.

        """
        n_figures_msg = (
            f'Expected {len(self.img_names)} figures (based  on the number of '
            f'image result filenames), but there are {len(figures)} figures '
            f'available. The most likely reason for this is that this test is '
            f'producing too many figures, (alternatively if not using '
            f'ImageCompare as a decorator, it is possible that a test run '
            f'prior to this one has not closed its figures).')
        assert len(figures) == len(self.img_names), n_figures_msg

        for img_name, figure in zip(self.img_names, figures):
            expected_path = self.expected_path(test_name, img_name, '.png')
            result_path = self.result_path(test_name, img_name, '.png')

            if not os.path.isdir(os.path.dirname(expected_path)):
                os.makedirs(os.path.dirname(expected_path))

            if not os.path.isdir(os.path.dirname(result_path)):
                os.makedirs(os.path.dirname(result_path))

            with flufl.lock.Lock(result_path + '.lock'):
                self.save_figure(figure, result_path)
                self.do_compare(result_path, expected_path, self.tolerance)

    def save_figure(self, figure, result_fname):
        """
        The actual call which saves the figure.

        Returns nothing.

        May be overridden to do figure based pre-processing (such
        as removing text objects etc.)
        """
        figure.savefig(result_fname)

    def do_compare(self, result_fname, expected_fname, tol):
        """
        Runs the comparison of the result file with the expected file.

        If an RMS difference greater than ``tol`` is found an assertion
        error is raised with an appropriate message with the paths to
        the files concerned.

        """
        if not os.path.exists(expected_fname):
            warnings.warn('Created image in %s' % expected_fname)
            shutil.copy2(result_fname, expected_fname)

        err = mcompare.compare_images(expected_fname, result_fname,
                                      tol=tol, in_decorator=True)

        if err:
            assert False, (
                f"Images were different (RMS: {err['rms']}).\n"
                f"{err['actual']} {err['expected']} {err['diff']}\n"
                f"Consider running idiff to inspect these differences.")

    def __call__(self, test_func):
        """Called when the decorator is applied to a function."""
        test_name = test_func.__name__
        mod_name = test_func.__module__
        if mod_name == '__main__':
            import sys
            fname = sys.modules[mod_name].__file__
            mod_name = os.path.basename(os.path.splitext(fname)[0])
        mod_name = mod_name.rsplit('.', 1)[-1]

        def wrapped(*args, **kwargs):
            orig_backend = plt.get_backend()
            plt.switch_backend('agg')
            mpl_setup()

            if plt.get_fignums():
                warnings.warn('Figures existed before running the %s %s test.'
                              ' All figures should be closed after they run. '
                              'They will be closed automatically now.' %
                              (mod_name, test_name))
                plt.close('all')

            with mpl.style.context(self.style):
                if MPL_VERSION >= packaging.version.parse('3.2.0'):
                    mpl.rcParams['text.kerning_factor'] = 6

                r = test_func(*args, **kwargs)

                figures = [plt.figure(num) for num in plt.get_fignums()]

                try:
                    self.run_figure_comparisons(figures, test_name=mod_name)
                finally:
                    for figure in figures:
                        plt.close(figure)
                    plt.switch_backend(orig_backend)
            return r

        # nose needs the function's name to be in the form "test_*" to
        # pick it up
        wrapped.__name__ = test_name
        return wrapped


def failed_images_iter():
    """
    Return a generator of [expected, actual, diff] filenames for all failed
    image tests since the test output directory was created.
    """
    baseline_img_dir = os.path.join(ImageTesting.root_image_results,
                                    'baseline_images', 'mpl')
    diff_dir = os.path.join(ImageTesting.image_output_directory)

    baselines = sorted(glob.glob(os.path.join(baseline_img_dir,
                                              '*', '*.png')))
    for expected_fname in baselines:
        # Get the relative path of the expected image 2 folders up.
        expected_rel = os.path.relpath(
            expected_fname, os.path.dirname(os.path.dirname(expected_fname)))
        result_fname = os.path.join(
            diff_dir, os.path.dirname(expected_rel),
            'result-' + os.path.basename(expected_rel))
        diff_fname = result_fname[:-4] + '-failed-diff.png'
        if os.path.exists(diff_fname):
            yield expected_fname, result_fname, diff_fname


def failed_images_html():
    """
    Generates HTML which shows the image failures side-by-side
    when viewed in a web browser.
    """
    data_uri_template = '<img alt="{alt}" src="data:image/png;base64,{img}">'

    def image_as_base64(fname):
        with open(fname, "rb") as fh:
            return base64.b64encode(fh.read()).decode("ascii")

    html = ['<!DOCTYPE html>', '<html>', '<body>']

    for expected, actual, diff in failed_images_iter():
        expected_html = data_uri_template.format(
            alt='expected', img=image_as_base64(expected))
        actual_html = data_uri_template.format(
            alt='actual', img=image_as_base64(actual))
        diff_html = data_uri_template.format(
            alt='diff', img=image_as_base64(diff))

        html.extend([expected, '<br>',
                     expected_html, actual_html, diff_html,
                     '<br><hr>'])

    html.extend(['</body>', '</html>'])
    return '\n'.join(html)


def show(projection, geometry):
    orig_backend = mpl.get_backend()
    plt.switch_backend('tkagg')

    if geometry.type == 'MultiPolygon' and 1:
        multi_polygon = geometry
        for polygon in multi_polygon:
            import cartopy.mpl.patch as patch
            paths = patch.geos_to_path(polygon)
            for pth in paths:
                patch = mpatches.PathPatch(pth, edgecolor='none',
                                           lw=0, alpha=0.2)
                plt.gca().add_patch(patch)
            line_string = polygon.exterior
            plt.plot(*zip(*line_string.coords),
                     marker='+', linestyle='-')
    elif geometry.type == 'MultiPolygon':
        multi_polygon = geometry
        for polygon in multi_polygon:
            line_string = polygon.exterior
            plt.plot(*zip(*line_string.coords),
                     marker='+', linestyle='-')

    elif geometry.type == 'MultiLineString':
        multi_line_string = geometry
        for line_string in multi_line_string:
            plt.plot(*zip(*line_string.coords),
                     marker='+', linestyle='-')

    elif geometry.type == 'LinearRing':
        plt.plot(*zip(*geometry.coords), marker='+', linestyle='-')

    if 1:
        # Whole map domain
        plt.autoscale()
    elif 0:
        # The left-hand triangle
        plt.xlim(-1.65e7, -1.2e7)
        plt.ylim(0.3e7, 0.65e7)
    elif 0:
        # The tip of the left-hand triangle
        plt.xlim(-1.65e7, -1.55e7)
        plt.ylim(0.3e7, 0.4e7)
    elif 1:
        # The very tip of the left-hand triangle
        plt.xlim(-1.632e7, -1.622e7)
        plt.ylim(0.327e7, 0.337e7)
    elif 1:
        # The tip of the right-hand triangle
        plt.xlim(1.55e7, 1.65e7)
        plt.ylim(0.3e7, 0.4e7)

    plt.plot(*zip(*projection.boundary.coords), marker='o',
             scalex=False, scaley=False, zorder=-1)

    plt.show()
    plt.switch_backend(orig_backend)
