"""
Classes and functions to register a collection of images
"""

import traceback
import re
import os
import shutil
import numpy as np
import pathlib
from skimage import transform, exposure, filters
from time import time
import tqdm
import pandas as pd
import pickle
import colour
import pyvips
from scipy import ndimage
import shapely
from copy import deepcopy
import json

from . import feature_matcher
from . import serial_rigid
from . import feature_detectors
from . import non_rigid_registrars
from . import valtils
from . import preprocessing
from . import slide_tools
from . import slide_io
from . import viz
from . import warp_tools
from . import serial_non_rigid

pyvips.cache_set_max(0)

# Destination directories #
CONVERTED_IMG_DIR = "images"
PROCESSED_IMG_DIR = "processed"
RIGID_REG_IMG_DIR = "rigid_registration"
NON_RIGID_REG_IMG_DIR = "non_rigid_registration"
DEFORMATION_FIELD_IMG_DIR = "deformation_fields"
OVERLAP_IMG_DIR = "overlaps"
REG_RESULTS_DATA_DIR = "data"
MICRO_REG_DIR = "micro_registration"
DISPLACEMENT_DIRS = os.path.join(REG_RESULTS_DATA_DIR, "displacements")
MASK_DIR = "masks"

# Default image processing #
DEFAULT_BRIGHTFIELD_CLASS = preprocessing.ColorfulStandardizer
DEFAULT_BRIGHTFIELD_PROCESSING_ARGS = {'c': preprocessing.DEFAULT_COLOR_STD_C, "h": 0}
DEFAULT_FLOURESCENCE_CLASS = preprocessing.ChannelGetter
DEFAULT_FLOURESCENCE_PROCESSING_ARGS = {"channel": "dapi", "adaptive_eq": True}
DEFAULT_NORM_METHOD = "img_stats"

# Default rigid registration parameters #
DEFAULT_FD = feature_detectors.VggFD
DEFAULT_TRANSFORM_CLASS = transform.SimilarityTransform
DEFAULT_MATCH_FILTER = feature_matcher.RANSAC_NAME
DEFAULT_SIMILARITY_METRIC = "n_matches"
DEFAULT_AFFINE_OPTIMIZER_CLASS = None
DEFAULT_MAX_PROCESSED_IMG_SIZE = 850
DEFAULT_MAX_IMG_DIM = 850
DEFAULT_THUMBNAIL_SIZE = 500
DEFAULT_MAX_NON_RIGID_REG_SIZE = 3000

# Tiled non-rigid registration arguments
TILER_THRESH_GB = 2
DEFAULT_NR_TILE_WH = 512

# Rigid registration kwarg keys #
AFFINE_OPTIMIZER_KEY = "affine_optimizer"
TRANSFORMER_KEY = "transformer"
SIM_METRIC_KEY = "similarity_metric"
FD_KEY = "feature_detector"
MATCHER_KEY = "matcher"
NAME_KEY = "name"
IMAGES_ORDERD_KEY = "imgs_ordered"
REF_IMG_KEY = "reference_img_f"
QT_EMMITER_KEY = "qt_emitter"
TFORM_SRC_SHAPE_KEY = "transformation_src_shape_rc"
TFORM_DST_SHAPE_KEY = "transformation_dst_shape_rc"
TFORM_MAT_KEY = "M"
CHECK_REFLECT_KEY = "check_for_reflections"

# Rigid registration kwarg keys #
NON_RIGID_REG_CLASS_KEY = "non_rigid_reg_class"
NON_RIGID_REG_PARAMS_KEY = "non_rigid_reg_params"
NON_RIGID_USE_XY_KEY = "moving_to_fixed_xy"
NON_RIGID_COMPOSE_KEY = "compose_transforms"

# Default non-rigid registration parameters #
DEFAULT_NON_RIGID_CLASS = non_rigid_registrars.OpticalFlowWarper
DEFAULT_NON_RIGID_KWARGS = {}

# Cropping options
CROP_OVERLAP = "overlap"
CROP_REF = "reference"
CROP_NONE = "all"


def init_jvm(jar=None, mem_gb=10):
    """Initialize JVM for BioFormats
    """
    slide_io.init_jvm(jar=None, mem_gb=10)


def kill_jvm():
    """Kill JVM for BioFormats
    """
    slide_io.kill_jvm()


def load_registrar(src_f):
    """Load a Valis object

    Parameters
    ----------
    src_f : string
        Path to pickled Valis object

    Returns
    -------
    registrar : Valis

        Valis object used for registration

    """
    registrar = pickle.load(open(src_f, 'rb'))

    data_dir = registrar.data_dir
    read_data_dir = os.path.split(src_f)[0]

    # If registrar has moved, will need to update paths to results
    # and displacement fields
    if data_dir != read_data_dir:
        new_dst_dir = os.path.split(read_data_dir)[0]
        registrar.dst_dir = new_dst_dir
        registrar.set_dst_paths()

        for slide_obj in registrar.slide_dict.values():
            slide_obj.update_results_img_paths()

    return registrar


class Slide(object):
    """Stores registration info and warps slides/points

    `Slide` is a class that stores registration parameters
    and other metadata about a slide. Once registration has been
    completed, `Slide` is also able warp the slide and/or points
    using the same registration parameters. Warped slides can be saved
    as ome.tiff images with valid ome-xml.

    Attributes
    ----------
    src_f : str
        Path to slide.

    image: ndarray
        Image to registered. Taken from a level in the image pyramid.
        However, image may be resized to fit within the `max_image_dim_px`
        argument specified when creating a `Valis` object.

    val_obj : Valis
        The "parent" object that registers all of the slide.

    reader : SlideReader
        Object that can read slides and collect metadata.

    original_xml : str
        Xml string created by bio-formats

    img_type : str
        Whether the image is "brightfield" or "fluorescence"

    is_rgb : bool
        Whether or not the slide is RGB.

    slide_shape_rc : tuple of int
        Dimensions of the largest resolution in the slide, in the form
        of (row, col).

    series : int
        Slide series to be read

    slide_dimensions_wh : ndarray
        Dimensions of all images in the pyramid (width, height).

    resolution : float
        Physical size of each pixel.

    units : str
        Physical unit of each pixel.

    name : str
        Name of the image. Usually `img_f` but with the extension removed.

    processed_img : ndarray
        Image used to perform registration

    rigid_reg_mask : ndarray
        Mask of convex hulls covering tissue in unregistered image.
        Could be used to mask `processed_img` before rigid registration

    non_rigid_reg_mask : ndarray
        Created by combining rigidly warped `rigid_reg_mask` in all
        other slides.

    stack_idx : int
        Position of image in sorted Z-stack

    processed_img_f : str
        Path to thumbnail of the processed `image`.

    rigid_reg_img_f : str
        Path to thumbnail of rigidly aligned `image`.

    non_rigid_reg_img_f : str
        Path to thumbnail of non-rigidly aligned `image`.

    processed_img_shape_rc : tuple of int
        Shape (row, col) of the processed image used to find the
        transformation parameters. Maximum dimension will be less or
        equal to the `max_processed_image_dim_px` specified when
        creating a `Valis` object. As such, this may be smaller than
        the image's shape.

    aligned_slide_shape_rc : tuple of int
        Shape (row, col) of aligned slide, based on the dimensions in the 0th
        level of they pyramid. In

    reg_img_shape_rc : tuple of int
        Shape (row, col) of the registered image

    M : ndarray
        Rigid transformation matrix that aligns `image` to the previous
        image in the stack. Found using the processed copy of `image`.

    bk_dxdy : ndarray
        (2, N, M) numpy array of pixel displacements in
        the x and y directions. dx = bk_dxdy[0], and dy=bk_dxdy[1]. Used
        to warp images. Found using the rigidly aligned version of the
        processed image.

    fwd_dxdy : ndarray
        Inverse of `bk_dxdy`. Used to warp points.

    _bk_dxdy_f : str
        Path to file containing bk_dxdy, if saved

    _fwd_dxdy_f : str
        Path to file containing fwd_dxdy, if saved

    _bk_dxdy_np : ndarray
        `bk_dxdy` as a numpy array. Only not None if `bk_dxdy` becomes
        associated with a file

    _fwd_dxdy_np : ndarray
        `fwd_dxdy` as a numpy array. Only not None if `fwd_dxdy` becomes
        associated with a file

    stored_dxdy : bool
        Whether or not the non-rigid displacements are saved in a file
        Should only occur if image is very large.

    fixed_slide : Slide
        Slide object to which this one was aligned.

    xy_matched_to_prev : ndarray
        Coordinates (x, y) of features in `image` that had matches in the
        previous image. Will have shape (N, 2)

    xy_in_prev : ndarray
        Coordinates (x, y) of features in the previous that had matches
        to those in `image`. Will have shape (N, 2)

    xy_matched_to_prev_in_bbox : ndarray
        Subset of `xy_matched_to_prev` that were within `overlap_mask_bbox_xywh`.
        Will either have shape (N, 2) or (M, 2), with M < N.

    xy_in_prev_in_bbox : ndarray
        Subset of `xy_in_prev` that were within `overlap_mask_bbox_xywh`.
        Will either have shape (N, 2) or (M, 2), with M < N.

    crop : str
        Crop method

    bg_px_pos_rc : tuple
        Position of pixel that has the background color

    bg_color : list, optional
        Color of background pixels

    """

    def __init__(self, src_f, image, val_obj, reader):
        """
        Parameters
        ----------
        src_f : str
            Path to slide.

        image: ndarray
            Image to registered. Taken from a level in the image pyramid.
            However, image may be resized to fit within the `max_image_dim_px`
            argument specified when creating a `Valis` object.

        val_obj : Valis
            The "parent" object that registers all of the slide.

        reader : SlideReader
            Object that can read slides and collect metadata.

        """

        self.src_f = src_f
        self.image = image
        self.val_obj = val_obj
        self.reader = reader

        # Metadata #
        self.is_rgb = reader.metadata.is_rgb
        self.img_type = reader.guess_image_type()
        self.slide_shape_rc = reader.metadata.slide_dimensions[0][::-1]
        self.series = reader.series
        self.slide_dimensions_wh = reader.metadata.slide_dimensions
        self.resolution = np.mean(reader.metadata.pixel_physical_size_xyu[0:2])
        self.units = reader.metadata.pixel_physical_size_xyu[2]
        self.original_xml = reader.metadata.original_xml

        self.name = valtils.get_name(src_f)

        # To be filled in during registration #
        self.processed_img = None
        self.rigid_reg_mask = None
        self.non_rigid_reg_mask = None # Created by combining rigid masks
        self.stack_idx = None

        self.aligned_slide_shape_rc = None
        self.processed_img_shape_rc = None
        self.reg_img_shape_rc = None
        self.M = None
        self.bk_dxdy = None
        self.fwd_dxdy = None

        self.stored_dxdy = False
        self._bk_dxdy_f = None
        self._fwd_dxdy_f = None
        self._bk_dxdy_np = None
        self._fwd_dxdy_np = None
        self.processed_img_f = None
        self.rigid_reg_img_f = None
        self.non_rigid_reg_img_f = None

        self.fixed_slide = None
        self.xy_matched_to_prev = None
        self.xy_in_prev = None
        self.xy_matched_to_prev_in_bbox = None
        self.xy_in_prev_in_bbox = None

        self.crop = None
        self.bg_px_pos_rc = (0, 0)
        self.bg_color = None

    def slide2image(self, level, series=None, xywh=None):
        """Convert slide to image

        Parameters
        -----------
        level : int
            Pyramid level

        series : int, optional
            Series number. Defaults to 0

        xywh : tuple of int, optional
            The region to be sliced from the slide. If None,
            then the entire slide will be converted. Otherwise
            xywh is the (top left x, top left y, width, height) of
            the region to be sliced.

        Returns
        -------
        img : ndarray
            An image of the slide or the region defined by xywh

        """

        img = self.reader.slide2image(level=level, series=series, xywh=xywh)

        return img

    def slide2vips(self, level, series=None, xywh=None):
        """Convert slide to pyvips.Image

        Parameters
        -----------
        level : int
            Pyramid level

        series : int, optional
            Series number. Defaults to 0

        xywh : tuple of int, optional
            The region to be sliced from the slide. If None,
            then the entire slide will be converted. Otherwise
            xywh is the (top left x, top left y, width, height) of
            the region to be sliced.

        Returns
        -------
        vips_slide : pyvips.Image
            An of the slide or the region defined by xywh

        """

        vips_img = self.reader.slide2vips(level=level, series=series, xywh=xywh)

        return vips_img

    def get_aligned_to_ref_slide_crop_xywh(self, ref_img_shape_rc, ref_M, scaled_ref_img_shape_rc=None):
        """Get bounding box used to crop slide to fit in reference image

        Parameters
        ----------
        ref_img_shape_rc : tuple of int
            shape of reference image used to find registration parameters, i.e. processed image)

        ref_M : ndarray
            Transformation matrix for the reference image

        scaled_ref_img_shape_rc : tuple of int, optional
            shape of scaled image with shape `img_shape_rc`, i.e. slide corresponding
            to the image used to find the registration parameters.

        Returns
        -------
        crop_xywh : tuple of int
            Bounding box of crop area (XYWH)

        mask : ndarray
            Mask covering reference image

        """

        mask , _ = self.val_obj.get_crop_mask(CROP_REF)

        if scaled_ref_img_shape_rc is not None:
            sxy = np.array([*scaled_ref_img_shape_rc[::-1]]) / np.array([*ref_img_shape_rc[::-1]])
        else:
            scaled_ref_img_shape_rc = ref_img_shape_rc
            sxy = np.ones(2)

        reg_txy = -ref_M[0:2, 2]
        slide_xywh = (*reg_txy*sxy, *scaled_ref_img_shape_rc[::-1])

        return slide_xywh, mask

    def get_overlap_crop_xywh(self, warped_img_shape_rc, scaled_warped_img_shape_rc=None):
        """Get bounding box used to crop slide to where all slides overlap

        Parameters
        ----------
        warped_img_shape_rc : tuple of int
            shape of registered image

        warped_scaled_img_shape_rc : tuple of int, optional
            shape of scaled registered image (i.e. registered slied)

        Returns
        -------
        crop_xywh : tuple of int
            Bounding box of crop area (XYWH)

        """
        mask , mask_bbox_xywh = self.val_obj.get_crop_mask(CROP_OVERLAP)

        if scaled_warped_img_shape_rc is not None:
            sxy = np.array([*scaled_warped_img_shape_rc[::-1]]) / np.array([*warped_img_shape_rc[::-1]])
        else:
            sxy = np.ones(2)

        to_slide_transformer = transform.SimilarityTransform(scale=sxy)
        overlap_bbox = warp_tools.bbox2xy(mask_bbox_xywh)
        scaled_overlap_bbox = to_slide_transformer(overlap_bbox)
        scaled_overlap_xywh = warp_tools.xy2bbox(scaled_overlap_bbox)

        scaled_overlap_xywh[2:] = np.ceil(scaled_overlap_xywh[2:])
        scaled_overlap_xywh = tuple(scaled_overlap_xywh.astype(int))

        return scaled_overlap_xywh, mask

    def get_crop_xywh(self, crop, out_shape_rc=None):
        """Get bounding box used to crop aligned slide

        Parameters
        ----------

        out_shape_rc : tuple of int, optional
            If crop is "reference", this should be the shape of scaled reference image, such
            as the unwarped slide that corresponds to the unwarped processed reference image.

            If crop is "overlap", this should be the shape of the registered slides.


        Returns
        -------
        crop_xywh : tuple of int
            Bounding box of crop area (XYWH)

        mask : ndarray
            Mask, before crop
        """

        ref_slide = self.val_obj.slide_dict[valtils.get_name(self.val_obj.reference_img_f)]
        if crop == CROP_REF:
            transformation_shape_rc = np.array(ref_slide.processed_img_shape_rc)
            crop_xywh, mask = self.get_aligned_to_ref_slide_crop_xywh(ref_img_shape_rc=transformation_shape_rc,
                                                                      ref_M=ref_slide.M,
                                                                      scaled_ref_img_shape_rc=out_shape_rc)
        elif crop == CROP_OVERLAP:
            transformation_shape_rc = np.array(ref_slide.reg_img_shape_rc)
            crop_xywh, mask = self.get_overlap_crop_xywh(warped_img_shape_rc=transformation_shape_rc,
                                                         scaled_warped_img_shape_rc=out_shape_rc)

        return crop_xywh, mask

    def get_crop_method(self, crop):
        """Get string or logic defining how to crop the image
        """
        if crop is True:
            crop_method = self.crop
        else:
            crop_method = crop

        do_crop = crop_method in [CROP_REF, CROP_OVERLAP]

        if do_crop:
            return crop_method
        else:
            return False

    def get_bg_color_px_pos(self):
        """Get position of pixel that has color used for background
        """
        if self.img_type == slide_tools.IHC_NAME:
            # RGB. Get brightest pixel
            eps = np.finfo("float").eps
            with colour.utilities.suppress_warnings(colour_usage_warnings=True):
                if 1 < self.image.max() <= 255 and np.issubdtype(self.image.dtype, np.integer):
                    cam = colour.convert(self.image/255 + eps, 'sRGB', 'CAM16UCS')
                else:
                    cam = colour.convert(self.image + eps, 'sRGB', 'CAM16UCS')

            lum = cam[..., 0]
            bg_px = np.unravel_index(np.argmax(lum, axis=None), lum.shape)
        else:
            # IF. Get darkest pixel
            sum_img = self.image.sum(axis=2)
            bg_px = np.unravel_index(np.argmin(sum_img, axis=None), sum_img.shape)

        self.bg_px_pos_rc = bg_px
        self.bg_color = list(self.image[bg_px])

    def update_results_img_paths(self):
        n_digits = len(str(self.val_obj.size))
        stack_id = str.zfill(str(self.stack_idx), n_digits)

        self.processed_img_f = os.path.join(self.val_obj.processed_dir, self.name + ".png")
        self.rigid_reg_img_f = os.path.join(self.val_obj.reg_dst_dir, f"{stack_id}_f{self.name}.png")
        self.non_rigid_reg_img_f = os.path.join(self.val_obj.non_rigid_dst_dir, f"{stack_id}_f{self.name}.png")
        if self.stored_dxdy:
            bk_dxdy_f, fwd_dxdy_f = self.get_displacement_f()
            self._bk_dxdy_f = bk_dxdy_f
            self._fwd_dxdy_f = fwd_dxdy_f

    def get_displacement_f(self):
        bk_dxdy_f = os.path.join(self.val_obj.displacements_dir, f"{self.name}_bk_dxdy.tiff")
        fwd_dxdy_f = os.path.join(self.val_obj.displacements_dir, f"{self.name}_fwd_dxdy.tiff")

        return bk_dxdy_f, fwd_dxdy_f

    def get_bk_dxdy(self):
        if self.stored_dxdy:
            bk_dxdy_f, _ = self.get_displacement_f()
            cropped_bk_dxdy = pyvips.Image.new_from_file(bk_dxdy_f)
            full_bk_dxdy = self.val_obj.pad_displacement(cropped_bk_dxdy,
                self.val_obj._full_displacement_shape_rc,
                self.val_obj._non_rigid_bbox)

            return full_bk_dxdy
        else:
            return self._bk_dxdy_np

    def set_bk_dxdy(self, bk_dxdy):
        """
        Only set if an array
        """
        if not isinstance(bk_dxdy, pyvips.Image):
            self._bk_dxdy_np = bk_dxdy
        else:
            print(f"Cannot set bk_dxdy when data is type {type(bk_dxdy)}")

    bk_dxdy = property(fget=get_bk_dxdy,
                       fset=set_bk_dxdy,
                       doc="Get and set backwards displacements")

    def get_fwd_dxdy(self):
        if self.stored_dxdy:
            _, fwd_dxdy_f = self.get_displacement_f()
            cropped_fwd_dxdy = pyvips.Image.new_from_file(fwd_dxdy_f)
            full_fwd_dxdy = self.val_obj.pad_displacement(cropped_fwd_dxdy,
                self.val_obj._full_displacement_shape_rc,
                self.val_obj._non_rigid_bbox)

            return full_fwd_dxdy

        else:
            return self._fwd_dxdy_np

    def set_fwd_dxdy(self, fwd_dxdy):
        if not isinstance(fwd_dxdy, pyvips.Image):
            self._fwd_dxdy_np = fwd_dxdy
        else:
            print(f"Cannot set fwd_dxdy when data is type {type(fwd_dxdy)}")

    fwd_dxdy = property(fget=get_fwd_dxdy,
                        fset=set_fwd_dxdy,
                        doc="Get forward displacements")

    def warp_img(self, img=None, non_rigid=True, crop=True, interp_method="bicubic"):
        """Warp an image using the registration parameters

        img : ndarray, optional
            The image to be warped. If None, then Slide.image
            will be warped.

        non_rigid : bool
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied.

        crop: bool, str
            How to crop the registered images. If `True`, then the same crop used
            when initializing the `Valis` object will be used. If `False`, the
            image will not be cropped. If "overlap", the warped slide will be
            cropped to include only areas where all images overlapped.
            "reference" crops to the area that overlaps with the reference image,
            defined by `reference_img_f` when initialzing the `Valis object`.

        interp_method : str
            Interpolation method used when warping slide. Default is "bicubic"

        Returns
        -------
        warped_img : ndarray
            Warped copy of `img`

        """

        if img is None:
            img = self.image

        if non_rigid:
            dxdy = self.bk_dxdy
        else:
            dxdy = None

        if isinstance(img, pyvips.Image):
            img_shape_rc = (img.width, img.height)
        else:
            img_shape_rc = img.shape[0:2]
        if not np.all(img_shape_rc == self.processed_img_shape_rc):
            msg = ("scaling transformation for image with different shape. "
                   "However, without knowing all of other image's shapes, "
                   "the scaling may not be the same for all images, and so"
                   "may not overlap."
                   )
            valtils.print_warning(msg)
            same_shape = False
            img_scale_rc = np.array(img_shape_rc)/(np.array(self.processed_img_shape_rc))
            out_shape_rc = self.val_obj.get_aligned_slide_shape(img_scale_rc)

        else:
            same_shape = True
            out_shape_rc = self.reg_img_shape_rc

        if isinstance(crop, bool) or isinstance(crop, str):
            crop_method = self.get_crop_method(crop)
            if crop_method is not False:
                if crop_method == CROP_REF:
                    ref_slide = self.val_obj.slide_dict[valtils.get_name(self.val_obj.reference_img_f)]
                    if not same_shape:
                        scaled_shape_rc = np.array(ref_slide.processed_img_shape_rc)*img_scale_rc
                    else:
                        scaled_shape_rc = ref_slide.processed_img_shape_rc
                elif crop_method == CROP_OVERLAP:
                    scaled_shape_rc = out_shape_rc

                bbox_xywh, _ = self.get_crop_xywh(crop_method, scaled_shape_rc)
            else:
                bbox_xywh = None

        elif isinstance(crop[0], (int, float)) and len(crop) == 4:
                bbox_xywh = crop
        else:
            bbox_xywh = None

        if img.ndim == self.image.ndim:
            bg_color = self.bg_color
        else:
            bg_color = None

        warped_img = \
            warp_tools.warp_img(img, M=self.M,
                                bk_dxdy=dxdy,
                                out_shape_rc=out_shape_rc,
                                transformation_src_shape_rc=self.processed_img_shape_rc,
                                transformation_dst_shape_rc=self.reg_img_shape_rc,
                                bbox_xywh=bbox_xywh,
                                bg_color=bg_color,
                                interp_method=interp_method)

        return warped_img


    def warp_img_from_to(self, img, to_slide_obj,
                        dst_slide_level=0, non_rigid=True, interp_method="bicubic", bg_color=None):

        """Warp an image from this slide onto another unwarped slide

        Note that if `img` is a labeled image then it is recommended to set `interp_method` to "nearest"

        Parameters
        ----------
        img : ndarray, pyvips.Image
            Image to warp. Should be a scaled version of the same one used for registration

        to_slide_obj : Slide
            Slide to which the points will be warped. I.e. `xy`
            will be warped from this Slide to their position in
            the unwarped slide associated with `to_slide_obj`.

        dst_slide_level: int, tuple, optional
            Pyramid level of the slide/image that `img` will be warped on to

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied.

        """

        if np.issubdtype(type(dst_slide_level), np.integer):
            to_slide_src_shape_rc = to_slide_obj.slide_dimensions_wh[dst_slide_level][::-1]
            aligned_slide_shape = self.val_obj.get_aligned_slide_shape(dst_slide_level)
        else:

            to_slide_src_shape_rc = np.array(dst_slide_level)

            dst_scale_rc = (to_slide_src_shape_rc/np.array(to_slide_obj.processed_img_shape_rc))
            aligned_slide_shape = np.round(dst_scale_rc*np.array(to_slide_obj.reg_img_shape_rc)).astype(int)

        if non_rigid:
            from_bk_dxdy = self.bk_dxdy
            to_fwd_dxdy = to_slide_obj.fwd_dxdy

        else:
            from_bk_dxdy = None
            to_fwd_dxdy = None

        warped_img = \
            warp_tools.warp_img_from_to(img,
                                        from_M=self.M,
                                        from_transformation_src_shape_rc=self.processed_img_shape_rc,
                                        from_transformation_dst_shape_rc=self.reg_img_shape_rc,
                                        from_dst_shape_rc=aligned_slide_shape,
                                        from_bk_dxdy=from_bk_dxdy,
                                        to_M=to_slide_obj.M,
                                        to_transformation_src_shape_rc=to_slide_obj.processed_img_shape_rc,
                                        to_transformation_dst_shape_rc=to_slide_obj.reg_img_shape_rc,
                                        to_src_shape_rc=to_slide_src_shape_rc,
                                        to_fwd_dxdy=to_fwd_dxdy,
                                        bg_color=bg_color,
                                        interp_method=interp_method
                                        )

        return warped_img



    @valtils.deprecated_args(crop_to_overlap="crop")
    def warp_slide(self, level, non_rigid=True, crop=True,
                   src_f=None, interp_method="bicubic"):
        """Warp a slide using registration parameters

        Parameters
        ----------
        level : int
            Pyramid level to be warped

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied. Default is True

        crop: bool, str
            How to crop the registered images. If `True`, then the same crop used
            when initializing the `Valis` object will be used. If `False`, the
            image will not be cropped. If "overlap", the warped slide will be
            cropped to include only areas where all images overlapped.
            "reference" crops to the area that overlaps with the reference image,
            defined by `reference_img_f` when initialzing the `Valis object`.

        src_f : str, optional
           Path of slide to be warped. If None (the default), Slide.src_f
           will be used. Otherwise, the file to which `src_f` points to should
           be an alternative copy of the slide, such as one that has undergone
           processing (e.g. stain segmentation), has a mask applied, etc...

        interp_method : str
            Interpolation method used when warping slide. Default is "bicubic"

        """
        if src_f is None:
            src_f = self.src_f

        if non_rigid:
            bk_dxdy = self.bk_dxdy
        else:
            bk_dxdy = None

        if level != 0:
            if not np.issubdtype(type(level), np.integer):
                msg = "Need slide level to be an integer indicating pyramid level"
                valtils.print_warning(msg)
            aligned_slide_shape = self.val_obj.get_aligned_slide_shape(level)
        else:
            aligned_slide_shape = self.aligned_slide_shape_rc

        if isinstance(crop, bool) or isinstance(crop, str):
            crop_method = self.get_crop_method(crop)
            if crop_method is not False:
                if crop_method == CROP_REF:
                    ref_slide = self.val_obj.slide_dict[valtils.get_name(self.val_obj.reference_img_f)]
                    scaled_aligned_shape_rc = ref_slide.slide_dimensions_wh[level][::-1]
                elif crop_method == CROP_OVERLAP:
                    scaled_aligned_shape_rc = aligned_slide_shape

                slide_bbox_xywh, _ = self.get_crop_xywh(crop=crop_method,
                                                        out_shape_rc=scaled_aligned_shape_rc)
                if crop_method == CROP_REF:
                    assert np.all(slide_bbox_xywh[2:]==scaled_aligned_shape_rc[::-1])
            else:
                slide_bbox_xywh = None

        elif isinstance(crop[0], (int, float)) and len(crop) == 4:
            slide_bbox_xywh = crop
        else:
            slide_bbox_xywh = None

        if src_f == self.src_f:
            bg_color = self.bg_color
        else:
            bg_color = None

        warped_slide = slide_tools.warp_slide(src_f, M=self.M,
                                              transformation_src_shape_rc=self.processed_img_shape_rc,
                                              transformation_dst_shape_rc=self.reg_img_shape_rc,
                                              aligned_slide_shape_rc=aligned_slide_shape,
                                              dxdy=bk_dxdy, level=level, series=self.series,
                                              interp_method=interp_method,
                                              bbox_xywh=slide_bbox_xywh,
                                              bg_color=bg_color)
        return warped_slide

    @valtils.deprecated_args(perceputally_uniform_channel_colors="colormap")
    def warp_and_save_slide(self, dst_f, level=0, non_rigid=True,
                            crop=True, src_f=None,
                            channel_names=None,
                            colormap=None,
                            interp_method="bicubic",
                            tile_wh=None, compression="lzw"):

        """Warp and save a slide

        Slides will be saved in the ome.tiff format.

        Parameters
        ----------
        dst_f : str
            Path to were the warped slide will be saved.

        level : int
            Pyramid level to be warped

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied. Default is True

        crop: bool, str
            How to crop the registered images. If `True`, then the same crop used
            when initializing the `Valis` object will be used. If `False`, the
            image will not be cropped. If "overlap", the warped slide will be
            cropped to include only areas where all images overlapped.
            "reference" crops to the area that overlaps with the reference image,
            defined by `reference_img_f` when initialzing the `Valis object`.

        channel_names : list, optional
            List of channel names. If None, then Slide.reader
            will attempt to find the channel names associated with `src_f`.

        colormap : dict, optional
            Dictionary of channel colors, where the key is the channel name, and the value the color as rgb255.
            If None (default), the channel colors from `current_ome_xml_str` will be used, if available.
            If None, and there are no channel colors in the `current_ome_xml_str`, then no colors will be added

        src_f : str, optional
           Path of slide to be warped. If None (the deffault), Slide.src_f
           will be used. Otherwise, the file to which `src_f` points to should
           be an alternative copy of the slide, such as one that has undergone
           processing (e.g. stain segmentation), has a mask applied, etc...

        interp_method : str
            Interpolation method used when warping slide. Default is "bicubic"

        tile_wh : int, optional
            Tile width and height used to save image

        compression : str
            Compression method used to save ome.tiff . Default is lzw, but can also
            be jpeg or jp2k. See pyips for more details.

        """

        warped_slide = self.warp_slide(level=level, non_rigid=non_rigid,
                                       crop=crop,
                                       interp_method=interp_method)

        # Get ome-xml #
        slide_meta = self.reader.metadata
        if slide_meta.pixel_physical_size_xyu[2] == slide_io.PIXEL_UNIT:
            px_phys_size = None
        else:
            px_phys_size = self.reader.scale_physical_size(level)

        if channel_names is None:
            if src_f is None:
                channel_names = slide_meta.channel_names
            else:
                reader_cls = slide_io.get_slide_reader(src_f)
                reader = reader_cls(src_f)
                channel_names = reader.metadata.channel_names

        bf_dtype = slide_io.vips2bf_dtype(warped_slide.format)
        out_xyczt = slide_io.get_shape_xyzct((warped_slide.width, warped_slide.height), warped_slide.bands)
        ome_xml_obj = slide_io.update_xml_for_new_img(current_ome_xml_str=slide_meta.original_xml,
                                                      new_xyzct=out_xyczt,
                                                      bf_dtype=bf_dtype,
                                                      is_rgb=self.is_rgb,
                                                      series=self.series,
                                                      pixel_physical_size_xyu=px_phys_size,
                                                      channel_names=channel_names,
                                                      colormap=colormap
                                                      )

        ome_xml = ome_xml_obj.to_xml()
        if tile_wh is None:
            tile_wh = slide_meta.optimal_tile_wh
            if level != 0:
                down_sampling = np.mean(slide_meta.slide_dimensions[level]/slide_meta.slide_dimensions[0])
                tile_wh = int(np.round(tile_wh*down_sampling))
                tile_wh = tile_wh - (tile_wh % 16)  # Tile shape must be multiple of 16
                if tile_wh < 16:
                    tile_wh = 16
                if np.any(np.array(out_xyczt[0:2]) < tile_wh):
                    tile_wh = min(out_xyczt[0:2])

        slide_io.save_ome_tiff(warped_slide, dst_f=dst_f, ome_xml=ome_xml,
                               tile_wh=tile_wh, compression=compression)

    def warp_xy(self, xy, M=None, slide_level=0, pt_level=0,
                non_rigid=True, crop=True):
        """Warp points using registration parameters

        Warps `xy` to their location in the registered slide/image

        Parameters
        ----------
        xy : ndarray
            (N, 2) array of points to be warped. Must be x,y coordinates

        slide_level: int, tuple, optional
            Pyramid level of the slide. Used to scale transformation matrices.
            Can also be the shape of the warped image (row, col) into which
            the points should be warped. Default is 0.

        pt_level: int, tuple, optional
            Pyramid level from which the points origingated. For example, if
            `xy` are from the centroids of cell segmentation performed on the
            full resolution image, this should be 0. Alternatively, the value can
            be a tuple of the image's shape (row, col) from which the points came.
            For example, if `xy` are  bounding box coordinates from an analysis on
            a lower resolution image, then pt_level is that lower resolution
            image's shape (row, col). Default is 0.

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied. Default is True.

        crop: bool, str
            Apply crop to warped points by shifting points to the mask's origin.
            Note that this can result in negative coordinates, but might be useful
            if wanting to draw the coordinates on the registered slide, such as
            annotation coordinates.

            If `True`, then the same crop used
            when initializing the `Valis` object will be used. If `False`, the
            image will not be cropped. If "overlap", the warped slide will be
            cropped to include only areas where all images overlapped.
            "reference" crops to the area that overlaps with the reference image,
            defined by `reference_img_f` when initialzing the `Valis object`.

        """
        if M is None:
            M = self.M

        if np.issubdtype(type(pt_level), np.integer):
            pt_dim_rc = self.slide_dimensions_wh[pt_level][::-1]
        else:
            pt_dim_rc = np.array(pt_level)

        if np.issubdtype(type(slide_level), np.integer):
            if slide_level != 0:
                if np.issubdtype(type(slide_level), np.integer):
                    aligned_slide_shape = self.val_obj.get_aligned_slide_shape(slide_level)
                else:
                    aligned_slide_shape = np.array(slide_level)
            else:
                aligned_slide_shape = self.aligned_slide_shape_rc
        else:
            aligned_slide_shape = np.array(slide_level)

        if non_rigid:
            fwd_dxdy = self.fwd_dxdy
        else:
            fwd_dxdy = None

        warped_xy = warp_tools.warp_xy(xy, M=M,
                                       transformation_src_shape_rc=self.processed_img_shape_rc,
                                       transformation_dst_shape_rc=self.reg_img_shape_rc,
                                       src_shape_rc=pt_dim_rc,
                                       dst_shape_rc=aligned_slide_shape,
                                       fwd_dxdy=fwd_dxdy)

        crop_method = self.get_crop_method(crop)
        if crop_method is not False:
            if crop_method == CROP_REF:
                ref_slide = self.val_obj.slide_dict[valtils.get_name(self.val_obj.reference_img_f)]
                if isinstance(slide_level, int):
                    scaled_aligned_shape_rc = ref_slide.slide_dimensions_wh[slide_level][::-1]
                else:
                    if len(slide_level) == 2:
                        scaled_aligned_shape_rc = slide_level
            elif crop_method == CROP_OVERLAP:
                scaled_aligned_shape_rc = aligned_slide_shape

            crop_bbox_xywh, _ = self.get_crop_xywh(crop_method, scaled_aligned_shape_rc)
            warped_xy -= crop_bbox_xywh[0:2]

        return warped_xy

    def warp_xy_from_to(self, xy, to_slide_obj, src_slide_level=0, src_pt_level=0,
                        dst_slide_level=0, non_rigid=True):

        """Warp points from this slide to another unwarped slide

        Takes a set of points found in this unwarped slide, and warps them to
        their position in the unwarped "to" slide.

        Parameters
        ----------
        xy : ndarray
            (N, 2) array of points to be warped. Must be x,y coordinates

        to_slide_obj : Slide
            Slide to which the points will be warped. I.e. `xy`
            will be warped from this Slide to their position in
            the unwarped slide associated with `to_slide_obj`.

        src_pt_level: int, tuple, optional
            Pyramid level of the slide/image in which `xy` originated.
            For example, if `xy` are from the centroids of cell segmentation
            performed on the unwarped full resolution image, this should be 0.
            Alternatively, the value can be a tuple of the image's shape (row, col)
            from which the points came. For example, if `xy` are  bounding
            box coordinates from an analysis on a lower resolution image,
            then pt_level is that lower resolution image's shape (row, col).

        dst_slide_level: int, tuple, optional
            Pyramid level of the slide/image in to `xy` will be warped.
            Similar to `src_pt_level`, if `dst_slide_level` is an int then
            the points will be warped to that pyramid level. If `dst_slide_level`
            is the "to" image's shape (row, col), then the points will be warped
            to their location in an image with that same shape.

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied.

        """

        if np.issubdtype(type(src_pt_level), np.integer):
            src_pt_dim_rc = self.slide_dimensions_wh[src_pt_level][::-1]
        else:
            src_pt_dim_rc = np.array(src_pt_level)

        if np.issubdtype(type(dst_slide_level), np.integer):
            to_slide_src_shape_rc = to_slide_obj.slide_dimensions_wh[dst_slide_level][::-1]
        else:
            to_slide_src_shape_rc = np.array(dst_slide_level)

        if src_slide_level != 0:
            if np.issubdtype(type(src_slide_level), np.integer):
                aligned_slide_shape = self.val_obj.get_aligned_slide_shape(src_slide_level)
            else:
                aligned_slide_shape = np.array(src_slide_level)
        else:
            aligned_slide_shape = self.aligned_slide_shape_rc

        if non_rigid:
            src_fwd_dxdy = self.fwd_dxdy
            dst_bk_dxdy = to_slide_obj.bk_dxdy

        else:
            src_fwd_dxdy = None
            dst_bk_dxdy = None

        xy_in_unwarped_to_img = \
            warp_tools.warp_xy_from_to(xy=xy,
                                       from_M=self.M,
                                       from_transformation_dst_shape_rc=self.reg_img_shape_rc,
                                       from_transformation_src_shape_rc=self.processed_img_shape_rc,
                                       from_dst_shape_rc=aligned_slide_shape,
                                       from_src_shape_rc=src_pt_dim_rc,
                                       from_fwd_dxdy=src_fwd_dxdy,
                                       to_M=to_slide_obj.M,
                                       to_transformation_src_shape_rc=to_slide_obj.processed_img_shape_rc,
                                       to_transformation_dst_shape_rc=to_slide_obj.reg_img_shape_rc,
                                       to_src_shape_rc=to_slide_src_shape_rc,
                                       to_dst_shape_rc=aligned_slide_shape,
                                       to_bk_dxdy=dst_bk_dxdy
                                       )

        return xy_in_unwarped_to_img

    def warp_geojson(self, geojson_f, M=None, slide_level=0, pt_level=0,
                non_rigid=True, crop=True):
        """Warp geometry using registration parameters

        Warps geometries to their location in the registered slide/image

        Parameters
        ----------
        geojson_f : str
            Path to geojson file containing the annotation geometries. Assumes
            coordinates are in pixels.

        slide_level: int, tuple, optional
            Pyramid level of the slide. Used to scale transformation matrices.
            Can also be the shape of the warped image (row, col) into which
            the points should be warped. Default is 0.

        pt_level: int, tuple, optional
            Pyramid level from which the points origingated. For example, if
            `xy` are from the centroids of cell segmentation performed on the
            full resolution image, this should be 0. Alternatively, the value can
            be a tuple of the image's shape (row, col) from which the points came.
            For example, if `xy` are  bounding box coordinates from an analysis on
            a lower resolution image, then pt_level is that lower resolution
            image's shape (row, col). Default is 0.

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied. Default is True.

        crop: bool, str
            Apply crop to warped points by shifting points to the mask's origin.
            Note that this can result in negative coordinates, but might be useful
            if wanting to draw the coordinates on the registered slide, such as
            annotation coordinates.

            If `True`, then the same crop used
            when initializing the `Valis` object will be used. If `False`, the
            image will not be cropped. If "overlap", the warped slide will be
            cropped to include only areas where all images overlapped.
            "reference" crops to the area that overlaps with the reference image,
            defined by `reference_img_f` when initialzing the `Valis object`.

        """
        if M is None:
            M = self.M

        if np.issubdtype(type(pt_level), np.integer):
            pt_dim_rc = self.slide_dimensions_wh[pt_level][::-1]
        else:
            pt_dim_rc = np.array(pt_level)

        if np.issubdtype(type(slide_level), np.integer):
            if slide_level != 0:
                if np.issubdtype(type(slide_level), np.integer):
                    aligned_slide_shape = self.val_obj.get_aligned_slide_shape(slide_level)
                else:
                    aligned_slide_shape = np.array(slide_level)
            else:
                aligned_slide_shape = self.aligned_slide_shape_rc
        else:
            aligned_slide_shape = np.array(slide_level)

        if non_rigid:
            fwd_dxdy = self.fwd_dxdy
        else:
            fwd_dxdy = None

        with open(geojson_f) as f:
            annotation_geojson = json.load(f)

        crop_method = self.get_crop_method(crop)
        if crop_method is not False:
            if crop_method == CROP_REF:
                ref_slide = self.val_obj.slide_dict[valtils.get_name(self.val_obj.reference_img_f)]
                if isinstance(slide_level, int):
                    scaled_aligned_shape_rc = ref_slide.slide_dimensions_wh[slide_level][::-1]
                else:
                    if len(slide_level) == 2:
                        scaled_aligned_shape_rc = slide_level
            elif crop_method == CROP_OVERLAP:
                scaled_aligned_shape_rc = aligned_slide_shape

            crop_bbox_xywh, _ = self.get_crop_xywh(crop_method, scaled_aligned_shape_rc)
            shift_xy = crop_bbox_xywh[0:2]
        else:
            shift_xy = None

        warped_features = [None]*len(annotation_geojson["features"])
        for i, ft in tqdm.tqdm(enumerate(annotation_geojson["features"])):
            geom = shapely.geometry.shape(ft["geometry"])
            warped_geom = warp_tools.warp_shapely_geom(geom, M=M,
                                            transformation_src_shape_rc=self.processed_img_shape_rc,
                                            transformation_dst_shape_rc=self.reg_img_shape_rc,
                                            src_shape_rc=pt_dim_rc,
                                            dst_shape_rc=aligned_slide_shape,
                                            fwd_dxdy=fwd_dxdy,
                                            shift_xy=shift_xy)
            warped_ft = deepcopy(ft)
            warped_ft["geometry"] = shapely.geometry.mapping(warped_geom)
            warped_features[i] = warped_ft

        warped_geojson = {"type":annotation_geojson["type"], "features":warped_features}

        return warped_geojson

    def warp_geojson_from_to(self, geojson_f, to_slide_obj, src_slide_level=0, src_pt_level=0,
                            dst_slide_level=0, non_rigid=True):
        """Warp geoms in geojson file from annotation slide to another unwarped slide

        Takes a set of geometries found in this annotation slide, and warps them to
        their position in the unwarped "to" slide.

        Parameters
        ----------
        geojson_f : str
            Path to geojson file containing the annotation geometries. Assumes
            coordinates are in pixels.

        to_slide_obj : Slide
            Slide to which the points will be warped. I.e. `xy`
            will be warped from this Slide to their position in
            the unwarped slide associated with `to_slide_obj`.

        src_pt_level: int, tuple, optional
            Pyramid level of the slide/image in which `xy` originated.
            For example, if `xy` are from the centroids of cell segmentation
            performed on the unwarped full resolution image, this should be 0.
            Alternatively, the value can be a tuple of the image's shape (row, col)
            from which the points came. For example, if `xy` are  bounding
            box coordinates from an analysis on a lower resolution image,
            then pt_level is that lower resolution image's shape (row, col).

        dst_slide_level: int, tuple, optional
            Pyramid level of the slide/image in to `xy` will be warped.
            Similar to `src_pt_level`, if `dst_slide_level` is an int then
            the points will be warped to that pyramid level. If `dst_slide_level`
            is the "to" image's shape (row, col), then the points will be warped
            to their location in an image with that same shape.

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied.

        Returns
        -------
        warped_geojson : dict
            Dictionry of warped geojson geometries

        """

        if np.issubdtype(type(src_pt_level), np.integer):
            src_pt_dim_rc = self.slide_dimensions_wh[src_pt_level][::-1]
        else:
            src_pt_dim_rc = np.array(src_pt_level)

        if np.issubdtype(type(dst_slide_level), np.integer):
            to_slide_src_shape_rc = to_slide_obj.slide_dimensions_wh[dst_slide_level][::-1]
        else:
            to_slide_src_shape_rc = np.array(dst_slide_level)

        if src_slide_level != 0:
            if np.issubdtype(type(src_slide_level), np.integer):
                aligned_slide_shape = self.val_obj.get_aligned_slide_shape(src_slide_level)
            else:
                aligned_slide_shape = np.array(src_slide_level)
        else:
            aligned_slide_shape = self.aligned_slide_shape_rc

        if non_rigid:
            src_fwd_dxdy = self.fwd_dxdy
            dst_bk_dxdy = to_slide_obj.bk_dxdy

        else:
            src_fwd_dxdy = None
            dst_bk_dxdy = None

        with open(geojson_f) as f:
            annotation_geojson = json.load(f)

        warped_features = [None]*len(annotation_geojson["features"])
        for i, ft in tqdm.tqdm(enumerate(annotation_geojson["features"])):
            geom = shapely.geometry.shape(ft["geometry"])
            warped_geom = warp_tools.warp_shapely_geom_from_to(geom=geom,
                                            from_M=self.M,
                                            from_transformation_dst_shape_rc=self.reg_img_shape_rc,
                                            from_transformation_src_shape_rc=self.processed_img_shape_rc,
                                            from_dst_shape_rc=aligned_slide_shape,
                                            from_src_shape_rc=src_pt_dim_rc,
                                            from_fwd_dxdy=src_fwd_dxdy,
                                            to_M=to_slide_obj.M,
                                            to_transformation_src_shape_rc=to_slide_obj.processed_img_shape_rc,
                                            to_transformation_dst_shape_rc=to_slide_obj.reg_img_shape_rc,
                                            to_src_shape_rc=to_slide_src_shape_rc,
                                            to_dst_shape_rc=aligned_slide_shape,
                                            to_bk_dxdy=dst_bk_dxdy
                                            )

            warped_ft = deepcopy(ft)
            warped_ft["geometry"] = shapely.geometry.mapping(warped_geom)
            warped_features[i] = warped_ft

        warped_geojson = {"type":annotation_geojson["type"], "features":warped_features}

        return warped_geojson


class Valis(object):
    """Reads, registers, and saves a series of slides/images

    Implements the registration pipeline described in
    "VALIS: Virtual Alignment of pathoLogy Image Series" by Gatenbee et al.
    This pipeline will read images and whole slide images (WSI) using pyvips,
    bioformats, or openslide, and so should work with a wide variety of formats.
    VALIS can perform both rigid and non-rigid registration. The registered slides
    can be saved as ome.tiff slides that can be used in downstream analyses. The
    ome.tiff format is opensource and widely supported, being readable in several
    different programming languages (Python, Java, Matlab, etc...) and software,
    such as QuPath or HALO.

    The pipeline is fully automated and goes as follows:

    1. Images/slides are converted to numpy arrays. As WSI are often
    too large to fit into memory, these images are usually lower resolution
    images from different pyramid levels.

    2. Images are processed to single channel images. They are then
    normalized to make them look as similar as possible.

    3. Image features are detected and then matched between all pairs of image.

    4. If the order of images is unknown, they will be optimally ordered
    based on their feature similarity

    5. Rigid registration is performed serially, with each image being
    rigidly aligned to the previous image in the stack.

    6. Non-rigid registration is then performed either by 1) aliging each image
    towards the center of the stack, composing the deformation fields
    along the way, or 2) using groupwise registration that non-rigidly aligns
    the images to a common frame of reference.

    7. Error is measured by calculating the distance between registered
    matched features.

    The transformations found by VALIS can then be used to warp the full
    resolution slides. It is also possible to merge non-RGB registered slides
    to create a highly multiplexed image. These aligned and/or merged slides
    can then be saved as ome.tiff images using pyvips.

    In addition to warping images and slides, VALIS can also warp point data,
    such as cell centoids or ROI coordinates.

    Attributes
    ----------
    name : str
        Descriptive name of registrar, such as the sample's name.

    src_dir: str
        Path to directory containing the slides that will be registered.

    dst_dir : str
        Path to where the results should be saved.

    original_img_list : list of ndarray
        List of images converted from the slides in `src_dir`

    slide_dims_dict_wh :
        Dictionary of slide dimensions. Only needed if dimensions not
        available in the slide/image's metadata.

    resolution_xyu: tuple
        Physical size per pixel and the unit.

    image_type : str
        Type of image, i.e. "brightfield" or "fluorescence"

    series : int
        Slide series to that was read.

    size : int
        Number of images to align

    aligned_img_shape_rc : tuple of int
        Shape (row, col) of aligned images

    aligned_slide_shape_rc : tuple of int
        Shape (row, col) of the aligned slides

    slide_dict : dict of Slide
        Dictionary of Slide objects, each of which contains information
        about a slide, and methods to warp it.

    brightfield_procsseing_fxn_str: str
        Name of function used to process brightfield images.

    if_procsseing_fxn_str : str
        Name of function used to process fluorescence images.

    max_image_dim_px : int
        Maximum width or height of images that will be saved.
        This limit is mostly to keep memory in check.

    max_processed_image_dim_px : int
        Maximum width or height of processed images. An important
        parameter, as it determines the size of of the image in which
        features will be detected and displacement fields computed.

    reference_img_f : str
        Filename of image that will be treated as the center of the stack.
        If None, the index of the middle image will be the reference.

    reference_img_idx : int
        Index of slide that corresponds to `reference_img_f`, after
        the `img_obj_list` has been sorted during rigid registration.

    align_to_reference : bool
        Whether or not images should be aligne to a reference image
        specified by `reference_img_f`. Will be set to True if
        `reference_img_f` is provided.

    crop: str, optional
        How to crop the registered images.

    rigid_registrar : SerialRigidRegistrar
        SerialRigidRegistrar object that performs the rigid registration.

    rigid_reg_kwargs : dict
        Dictionary of keyward arguments passed to
        `serial_rigid.register_images`.

    feature_descriptor_str : str
        Name of feature descriptor.

    feature_detector_str : str
        Name of feature detector.

    transform_str : str
        Name of rigid transform

    similarity_metric : str
        Name of similarity metric used to order slides.

    match_filter_method : str
        Name of method used to filter out poor feature matches.

    non_rigid_registrar : SerialNonRigidRegistrar
        SerialNonRigidRegistrar object that performs serial
        non-rigid registration.

    non_rigid_reg_kwargs : dict
        Dictionary of keyward arguments passed to
        `serial_non_rigid.register_images`.

    non_rigid_registrar_cls : NonRigidRegistrar
        Uninstantiated NonRigidRegistrar class that will be used
        by `non_rigid_registrar` to calculate the deformation fields
        between images.

    non_rigid_reg_class_str : str
        Name of the of class `non_rigid_registrar_cls` belongs to.

    thumbnail_size : int
        Maximum width or height of thumbnails that show results

    original_overlap_img : ndarray
        Image showing how original images overlap before registration.
        Created by merging coloring the inverted greyscale copies of each
        image, and then merging those images.

    rigid_overlap_img : ndarray
        Image showing how images overlap after rigid registration.

    non_rigid_overlap_img : ndarray
        Image showing how images overlap after rigid + non-rigid registration.

    has_rounds : bool
        Whether or not the contents of `src_dir` contain subdirectories that
        have single images spread across multiple files. An example would be
        .ndpis images.

    norm_method : str
        Name of method used to normalize the processed images

    target_processing_stats : ndarray
        Array of processed images' stats used to normalize all images

    summary_df : pd.Dataframe
        Pandas dataframe containing information about the results, such
        as the error, shape of aligned slides, time to completion, etc...

    start_time : float
        The time at which registation was initiated.

    end_rigid_time : float
        The time at which rigid registation was completed.

    end_non_rigid_time : float
        The time at which non-rigid registation was completed.

    qt_emitter : PySide2.QtCore.Signal
        Used to emit signals that update the GUI's progress bars

    Examples
    --------

    Basic example using default parameters

    >>> from valis import registration, data
    >>> slide_src_dir = data.dcis_src_dir
    >>> results_dst_dir = "./slide_registration_example"
    >>> registered_slide_dst_dir = "./slide_registration_example/registered_slides"

    Perform registration

    >>> rigid_registrar, non_rigid_registrar, error_df = registrar.register()

    View results in "./slide_registration_example".
    If they look good, warp and save the slides as ome.tiff

    >>> registrar.warp_and_save_slides(registered_slide_dst_dir)

    This example shows how to register CyCIF images and then merge
    to create a high dimensional ome.tiff slide

    >>> registrar = registration.Valis(slide_src_dir, results_dst_dir)
    >>> rigid_registrar, non_rigid_registrar, error_df = registrar.register()

    Create function to get marker names from each slides' filename

    >>> def cnames_from_filename(src_f):
    ...     f = valtils.get_name(src_f)
    ...     return ["DAPI"] + f.split(" ")[1:4]
    ...
    >>> channel_name_dict = {f:cnames_from_filename(f) for f in  registrar.original_img_list}
    >>> merged_img, channel_names, ome_xml = registrar.warp_and_merge_slides(merged_slide_dst_f, channel_name_dict=channel_name_dict)

    View ome.tiff, located at merged_slide_dst_f

    """

    def __init__(self, src_dir, dst_dir, series=None, name=None, img_type=None,
                 feature_detector_cls=DEFAULT_FD,
                 transformer_cls=DEFAULT_TRANSFORM_CLASS,
                 affine_optimizer_cls=DEFAULT_AFFINE_OPTIMIZER_CLASS,
                 similarity_metric=DEFAULT_SIMILARITY_METRIC,
                 match_filter_method=DEFAULT_MATCH_FILTER,
                 imgs_ordered=False,
                 non_rigid_registrar_cls=DEFAULT_NON_RIGID_CLASS,
                 non_rigid_reg_params=DEFAULT_NON_RIGID_KWARGS,
                 compose_non_rigid=False,
                 img_list=None,
                 reference_img_f=None,
                 align_to_reference=False,
                 do_rigid=True,
                 crop=None,
                 create_masks=True,
                 check_for_reflections=False,
                 resolution_xyu=None, slide_dims_dict_wh=None,
                 max_image_dim_px=DEFAULT_MAX_IMG_DIM,
                 max_processed_image_dim_px=DEFAULT_MAX_PROCESSED_IMG_SIZE,
                 max_non_rigid_registartion_dim_px=DEFAULT_MAX_PROCESSED_IMG_SIZE,
                 thumbnail_size=DEFAULT_THUMBNAIL_SIZE,
                 norm_method=DEFAULT_NORM_METHOD, qt_emitter=None):

        """
        src_dir: str
            Path to directory containing the slides that will be registered.

        dst_dir : str
            Path to where the results should be saved.

        name : str, optional
            Descriptive name of registrar, such as the sample's name

        series : int, optional
            Slide series to that was read. If None, series will be set to 0.

        img_type : str, optional
            The type of image, either "brightfield", "fluorescence",
            or "multi". If None, VALIS will guess `img_type`
            of each image, based on the number of channels and datatype.
            Will assume that RGB = "brightfield",
            otherwise `img_type` will be set to "fluorescence".

        feature_detector_cls : FeatureDD, optional
            Uninstantiated FeatureDD object that detects and computes
            image features. Default is VggFD. The
            available feature_detectors are found in the `feature_detectors`
            module. If a desired feature detector is not available,
            one can be created by subclassing `feature_detectors.FeatureDD`.

        transformer_cls : scikit-image Transform class, optional
            Uninstantiated scikit-image transformer used to find
            transformation matrix that will warp each image to the target
            image. Default is SimilarityTransform

        affine_optimizer_cls : AffineOptimzer class, optional
            Uninstantiated AffineOptimzer that will minimize a
            cost function to find the optimal affine transformations.
            If a desired affine optimization is not available,
            one can be created by subclassing `affine_optimizer.AffineOptimizer`.

        similarity_metric : str, optional
            Metric used to calculate similarity between images, which is in
            turn used to build the distance matrix used to sort the images.
            Can be "n_matches", or a string to used as
            distance in spatial.distance.cdist. "n_matches"
            is the number of matching features between image pairs.

        match_filter_method: str, optional
            "GMS" will use filter_matches_gms() to remove poor matches.
            This uses the Grid-based Motion Statistics (GMS) or RANSAC.

        imgs_ordered : bool, optional
            Boolean defining whether or not the order of images in img_dir
            are already in the correct order. If True, then each filename should
            begin with the number that indicates its position in the z-stack. If
            False, then the images will be sorted by ordering a feature distance
            matix. Default is False.

        reference_img_f : str, optional
            Filename of image that will be treated as the center of the stack.
            If None, the index of the middle image will be the reference.

        align_to_reference : bool, optional
            If `False`, images will be non-rigidly aligned serially towards the
            reference image. If `True`, images will be non-rigidly aligned
            directly to the reference image. If `reference_img_f` is None,
            then the reference image will be the one in the middle of the stack.

        non_rigid_registrar_cls : NonRigidRegistrar, optional
            Uninstantiated NonRigidRegistrar class that will be used to
            calculate the deformation fields between images. See
            the `non_rigid_registrars` module for a desciption of available
            methods. If a desired non-rigid registration method is not available,
            one can be implemented by subclassing.NonRigidRegistrar.
            If None, then only rigid registration will be performed

        non_rigid_reg_params: dictionary, optional
            Dictionary containing key, value pairs to be used to initialize
            `non_rigid_registrar_cls`.
            In the case where simple ITK is used by the, params should be
            a SimpleITK.ParameterMap. Note that numeric values nedd to be
            converted to strings. See the NonRigidRegistrar classes in
            `non_rigid_registrars` for the available non-rigid registration
            methods and arguments.

        compose_non_rigid : bool, optional
            Whether or not to compose non-rigid transformations. If `True`,
            then an image is non-rigidly warped before aligning to the
            adjacent non-rigidly aligned image. This allows the transformations
            to accumulate, which may bring distant features together but could
            also  result  in un-wanted deformations, particularly around the edges.
            If `False`, the image not warped before being aaligned to the adjacent
            non-rigidly aligned image. This can reduce unwanted deformations, but
            may not bring distant features together.

        do_rigid: bool, dictionary, optional
            Whether or not to perform rigid registration. If `False`, rigid
            registration will be skipped.

            If `do_rigid` is a dictionary, it should contain inverse transformation
            matrices to rigidly align images to the specificed by `reference_img_f`.
            M will be estimated for images that are not in the dictionary.
            Each key is the filename of the image associated with the transformation matrix,
            and value is a dictionary containing the following values:
                `M` : (required) a 3x3 inverse transformation matrix as a numpy array.
                      Found by determining how to align fixed to moving.
                      If `M` was found by determining how to align moving to fixed,
                      then `M` will need to be inverted first.
                `transformation_src_shape_rc` : (optional) shape (row, col) of image used to find the rigid transformation.
                      If not provided, then it is assumed to be the shape of the level 0 slide
                `transformation_dst_shape_rc` : (optional) shape of registered image.
                      If not provided, this is assumed to be the shape of the level 0 reference slide.

        crop: str, optional
            How to crop the registered images. "overlap" will crop to include
            only areas where all images overlapped. "reference" crops to the
            area that overlaps with a reference image, defined by
            `reference_img_f`. This option can be used even if `reference_img_f`
            is `None` because the reference image will be set as the one at the center
            of the stack.

            If both `crop` and `reference_img_f` are `None`, `crop`
            will be set to "overlap". If `crop` is None, but `reference_img_f`
            is defined, then `crop` will be set to "reference".

        create_masks : bool, optional
            Whether or not to create and apply masks for registration.
            Can help focus alignment on the tissue, but can sometimes
            mask too much if there is a lot of variation in the image.

        check_for_reflections : bool, optional
            Determine if alignments are improved by relfecting/mirroring/flipping
            images. Optional because it requires re-detecting features in each version
            of the images and then re-matching features, and so can be time consuming and
            not always necessary.

        resolution_xyu: tuple, optional
            Physical size per pixel and the unit. If None (the default), these
            values will be determined for each slide using the slides' metadata.
            If provided, this physical pixel sizes will be used for all of the slides.
            This option is available in case one cannot easily access to the original
            slides, but does have the information on pixel's physical units.

        slide_dims_dict_wh : dict, optional
            Key= slide/image file name,
            value= dimensions = [(width, height), (width, height), ...] for each level.
            If None (the default), the slide dimensions will be pulled from the
            slides' metadata. If provided, those values will be overwritten. This
            option is available in case one cannot easily access to the original
            slides, but does have the information on the slide dimensions.

        max_image_dim_px : int, optional
            Maximum width or height of images that will be saved.
            This limit is mostly to keep memory in check.

        max_processed_image_dim_px : int, optional
            Maximum width or height of processed images. An important
            parameter, as it determines the size of of the image in which
            features will be detected and displacement fields computed.

        max_non_rigid_registartion_dim_px : int, optional
             Maximum width or height of images used for non-rigid registration.
             Larger values may yeild more accurate results, at the expense of
             speed and memory. There is also a practical limit, as the specified
             size may be too large to fit in memory.

        mask_dict : dictionary
            Dictionary where key = overlap type (all, overlap, or reference), and
            value = (mask, mask_bbox_xywh)

        thumbnail_size : int, optional
            Maximum width or height of thumbnails that show results

        norm_method : str
            Name of method used to normalize the processed images. Options
            are "histo_match" for histogram matching, "img_stats" for normalizing by
            image statistics. See preprocessing.match_histograms
            and preprocessing.norm_khan for details.

        _non_rigid_bbox : list
            Bounding box of area in which non-rigid registration was conducted

        _full_displacement_shape_rc : tuple
            Shape of full displacement field. Would be larger than `_non_rigid_bbox`
            if non-rigid registration only performed in a masked region

        qt_emitter : PySide2.QtCore.Signal, optional
            Used to emit signals that update the GUI's progress bars

        """

        if name is None:
            name = os.path.split(src_dir)[1]
        self.name = name.replace(" ", "_")

        # Set paths #
        self.src_dir = src_dir
        self.dst_dir = os.path.join(dst_dir, self.name)
        if img_list is not None:
            self.original_img_list = img_list
        else:
            self.get_imgs_in_dir()
        self.set_dst_paths()

        # Some information may already be provided #
        self.slide_dims_dict_wh = slide_dims_dict_wh
        self.resolution_xyu = resolution_xyu
        self.image_type = img_type

        # Results fields #
        self.series = series
        self.size = 0
        self.aligned_img_shape_rc = None
        self.aligned_slide_shape_rc = None
        self.slide_dict = {}

        # Fields related to image pre-processing #
        self.brightfield_procsseing_fxn_str = None
        self.if_procsseing_fxn_str = None

        if max_image_dim_px < max_processed_image_dim_px:
            msg = f"max_image_dim_px is {max_image_dim_px} but needs to be less or equal to {max_processed_image_dim_px}. Setting max_image_dim_px to {max_processed_image_dim_px}"
            valtils.print_warning(msg)
            max_image_dim_px = max_processed_image_dim_px

        self.max_image_dim_px = max_image_dim_px
        self.max_processed_image_dim_px = max_processed_image_dim_px
        self.max_non_rigid_registartion_dim_px = max_non_rigid_registartion_dim_px

        # Setup rigid registration #
        self.reference_img_idx = None
        self.reference_img_f = reference_img_f
        self.align_to_reference = align_to_reference

        self.do_rigid = do_rigid
        self.rigid_registrar = None
        self._set_rigid_reg_kwargs(name=name,
                                   feature_detector=feature_detector_cls,
                                   similarity_metric=similarity_metric,
                                   match_filter_method=match_filter_method,
                                   transformer=transformer_cls,
                                   affine_optimizer=affine_optimizer_cls,
                                   imgs_ordered=imgs_ordered,
                                   reference_img_f=reference_img_f,
                                   check_for_reflections=check_for_reflections,
                                   qt_emitter=qt_emitter)

        # Setup non-rigid registration #
        self.non_rigid_registrar = None
        self.non_rigid_registrar_cls = non_rigid_registrar_cls

        if crop is None:
            if reference_img_f is None:
                self.crop = CROP_OVERLAP
            else:
                self.crop = CROP_REF
        else:
            self.crop = crop

        self.compose_non_rigid = compose_non_rigid
        if non_rigid_registrar_cls is not None:
            self._set_non_rigid_reg_kwargs(name=name,
                                           non_rigid_reg_class=non_rigid_registrar_cls,
                                           non_rigid_reg_params=non_rigid_reg_params,
                                           reference_img_f=reference_img_f,
                                           compose_non_rigid=compose_non_rigid,
                                           qt_emitter=qt_emitter)

        # Info realted to saving images to view results #
        self.mask_dict = None
        self.create_masks = create_masks

        self.thumbnail_size = thumbnail_size
        self.original_overlap_img = None
        self.rigid_overlap_img = None
        self.non_rigid_overlap_img = None
        self.micro_reg_overlap_img = None

        self.has_rounds = False
        self.norm_method = norm_method
        self.summary_df = None
        self.start_time = None
        self.end_rigid_time = None
        self.end_non_rigid_time = None

    def _set_rigid_reg_kwargs(self, name, feature_detector, similarity_metric,
                              match_filter_method, transformer, affine_optimizer,
                              imgs_ordered, reference_img_f, check_for_reflections, qt_emitter):

        """Set rigid registration kwargs
        Keyword arguments will be passed to `serial_rigid.register_images`

        """

        matcher = feature_matcher.Matcher(match_filter_method=match_filter_method)
        if affine_optimizer is not None:
            afo = affine_optimizer(transform=transformer.__name__)
        else:
            afo = affine_optimizer

        self.rigid_reg_kwargs = {NAME_KEY: name,
                                 FD_KEY: feature_detector(),
                                 SIM_METRIC_KEY: similarity_metric,
                                 TRANSFORMER_KEY: transformer(),
                                 MATCHER_KEY: matcher,
                                 AFFINE_OPTIMIZER_KEY: afo,
                                 REF_IMG_KEY: reference_img_f,
                                 IMAGES_ORDERD_KEY: imgs_ordered,
                                 CHECK_REFLECT_KEY: check_for_reflections,
                                 QT_EMMITER_KEY: qt_emitter
                                 }

        # Save methods as strings since some objects cannot be pickled #
        self.feature_descriptor_str = self.rigid_reg_kwargs[FD_KEY].kp_descriptor_name
        self.feature_detector_str = self.rigid_reg_kwargs[FD_KEY].kp_detector_name
        self.transform_str = self.rigid_reg_kwargs[TRANSFORMER_KEY].__class__.__name__
        self.similarity_metric = self.rigid_reg_kwargs[SIM_METRIC_KEY]
        self.match_filter_method = match_filter_method
        self.imgs_ordered = imgs_ordered

    def _set_non_rigid_reg_kwargs(self, name, non_rigid_reg_class, non_rigid_reg_params,
                                  reference_img_f, compose_non_rigid, qt_emitter):
        """Set non-rigid registration kwargs
        Keyword arguments will be passed to `serial_non_rigid.register_images`

        """

        self.non_rigid_reg_kwargs = {NAME_KEY: name,
                                     NON_RIGID_REG_CLASS_KEY: non_rigid_reg_class,
                                     NON_RIGID_REG_PARAMS_KEY: non_rigid_reg_params,
                                     REF_IMG_KEY: reference_img_f,
                                     QT_EMMITER_KEY: qt_emitter,
                                     NON_RIGID_COMPOSE_KEY: compose_non_rigid
                                     }

        self.non_rigid_reg_class_str = self.non_rigid_reg_kwargs[NON_RIGID_REG_CLASS_KEY].__name__

    def get_imgs_in_dir(self):
        """Get all images in Valis.src_dir

        """
        full_path_list = [os.path.join(self.src_dir, f) for f in os.listdir(self.src_dir)]
        self.original_img_list = []
        img_names = []
        for f in full_path_list:
            if os.path.isfile(f):
                if slide_tools.get_img_type(f) is not None:
                    self.original_img_list.append(f)
                    img_names.append(valtils.get_name(f))

        for f in full_path_list:
            if os.path.isdir(f):
                dir_name = os.path.split(f)[1]
                is_round, master_slide = slide_tools.determine_if_staining_round(f)
                if is_round:
                    self.original_img_list.append(master_slide)

                else:
                    # Some formats, like .mrxs have the main file but
                    # data in a subdirectory with the same name
                    matching_f = [ff for ff in full_path_list if re.search(dir_name, ff) is not None and os.path.split(ff)[1] != dir_name]
                    if len(matching_f) == 1:
                        if not matching_f[0] in self.original_img_list:
                            # Make sure that file not already in list
                            self.original_img_list.extend(matching_f)
                            img_names.append(dir_name)

                    elif len(matching_f) > 1:
                        msg = f"found {len(matching_f)} matches for {dir_name}: {', '.join(matching_f)}"
                        valtils.print_warning(msg)
                    elif len(matching_f) == 0:
                        msg = f"Can't find slide file associated with {dir_name}"
                        valtils.print_warning(msg)

    def set_dst_paths(self):
        """Set paths to where the results will be saved.

        """

        self.img_dir = os.path.join(self.dst_dir, CONVERTED_IMG_DIR)
        self.processed_dir = os.path.join(self.dst_dir, PROCESSED_IMG_DIR)
        self.reg_dst_dir = os.path.join(self.dst_dir, RIGID_REG_IMG_DIR)
        self.non_rigid_dst_dir = os.path.join(self.dst_dir, NON_RIGID_REG_IMG_DIR)
        self.deformation_field_dir = os.path.join(self.dst_dir, DEFORMATION_FIELD_IMG_DIR)
        self.overlap_dir = os.path.join(self.dst_dir, OVERLAP_IMG_DIR)
        self.data_dir = os.path.join(self.dst_dir, REG_RESULTS_DATA_DIR)
        self.displacements_dir = os.path.join(self.dst_dir, DISPLACEMENT_DIRS)
        self.micro_reg_dir = os.path.join(self.dst_dir, MICRO_REG_DIR)
        self.mask_dir = os.path.join(self.dst_dir, MASK_DIR)

    def get_ref_slide(self):
        ref_slide = self.slide_dict[valtils.get_name(self.reference_img_f)]

        return ref_slide

    def convert_imgs(self, series=None, reader_cls=None):
        """Convert slides to images and create dictionary of Slides.

        series : int, optional
            Slide series to be read. If None, the series with largest image will be read

        reader_cls : SlideReader, optional
            Uninstantiated SlideReader class that will convert
            the slide to an image, and also collect metadata.

        """

        img_types = []
        self.size = 0
        for f in tqdm.tqdm(self.original_img_list):
            if reader_cls is None:
                reader_cls = slide_io.get_slide_reader(f, series=series)

            reader = reader_cls(f, series=series)

            slide_dims = reader.metadata.slide_dimensions
            levels_in_range = np.where(slide_dims.max(axis=1) < self.max_image_dim_px)[0]
            if len(levels_in_range) > 0:
                level = levels_in_range[0]
            else:
                level = len(slide_dims) - 1

            vips_img = reader.slide2vips(level=level)

            scaling = np.min(self.max_image_dim_px/np.array([vips_img.width, vips_img.height]))
            if scaling < 1:
                vips_img = warp_tools.rescale_img(vips_img, scaling)

            img = warp_tools.vips2numpy(vips_img)

            slide_obj = Slide(f, img, self, reader)
            slide_obj.crop = self.crop
            img_types.append(slide_obj.img_type)

            # Will overwrite data if provided. Can occur if reading images, not the actual slides #
            if self.slide_dims_dict_wh is not None:
                matching_slide = [k for k in self.slide_dims_dict_wh.keys()
                                  if valtils.get_name(k) == slide_obj.name][0]

                slide_dims = self.slide_dims_dict_wh[matching_slide]
                if slide_dims.ndim == 1:
                    slide_dims = np.array([[slide_dims]])
                slide_obj.slide_shape_rc = slide_dims[0][::-1]

            if self.resolution_xyu is not None:
                slide_obj.resolution = np.mean(self.resolution_xyu[0:2])
                slide_obj.units = self.resolution_xyu[2]

            self.slide_dict[slide_obj.name] = slide_obj
            self.size += 1

        if self.image_type is None:
            unique_img_types = list(set(img_types))
            if len(unique_img_types) > 1:
                self.image_type = slide_tools.MULTI_MODAL_NAME
            else:
                self.image_type = unique_img_types[0]

        self.check_img_max_dims()

    def check_img_max_dims(self):
        """Ensure that all images have similar sizes.

        `max_image_dim_px` will be set to the maximum dimension of the
        smallest image if that value is less than max_image_dim_px

        """

        og_img_sizes_wh = np.array([slide_obj.image.shape[0:2][::-1] for slide_obj in self.slide_dict.values()])
        img_max_dims = og_img_sizes_wh.max(axis=1)
        min_max_wh = img_max_dims.min()
        scaling_for_og_imgs = min_max_wh/img_max_dims

        if np.any(scaling_for_og_imgs < 1):
            msg = f"Smallest image is less than max_image_dim_px. parameter max_image_dim_px is being set to {min_max_wh}"
            valtils.print_warning(msg)
            self.max_image_dim_px = min_max_wh
            for slide_obj in self.slide_dict.values():
                # Rescale images
                scaling = self.max_image_dim_px/max(slide_obj.image.shape[0:2])
                assert scaling <= self.max_image_dim_px
                if scaling < 1:
                    slide_obj.image =  warp_tools.rescale_img(slide_obj.image, scaling)

        if self.max_processed_image_dim_px > self.max_image_dim_px:
            msg = f"parameter max_processed_image_dim_px also being updated to {self.max_image_dim_px}"
            valtils.print_warning(msg)
            self.max_processed_image_dim_px = self.max_image_dim_px

    def create_original_composite_img(self, rigid_registrar):
        """Create imaage showing how images overlap before registration
        """

        min_r = np.inf
        max_r = 0
        min_c = np.inf
        max_c = 0
        composite_img_list = [None] * self.size
        for i, img_obj in enumerate(rigid_registrar.img_obj_list):
            img = img_obj.image
            padded_img = transform.warp(img, img_obj.T, preserve_range=True,
                                        output_shape=img_obj.padded_shape_rc)

            composite_img_list[i] = padded_img

            img_corners_rc = warp_tools.get_corners_of_image(img.shape[0:2])
            warped_corners_xy = warp_tools.warp_xy(img_corners_rc[:, ::-1], img_obj.T)
            min_r = min(warped_corners_xy[:, 1].min(), min_r)
            max_r = max(warped_corners_xy[:, 1].max(), max_r)
            min_c = min(warped_corners_xy[:, 0].min(), min_c)
            max_c = max(warped_corners_xy[:, 0].max(), max_c)

        composite_img = np.dstack(composite_img_list)
        cmap = viz.jzazbz_cmap()
        channel_colors = viz.get_n_colors(cmap, composite_img.shape[2])
        overlap_img = viz.color_multichannel(composite_img, channel_colors,
                                             rescale_channels=True,
                                             normalize_by="channel",
                                             cspace="CAM16UCS")

        min_r = int(min_r)
        max_r = int(np.ceil(max_r))
        min_c = int(min_c)
        max_c = int(np.ceil(max_c))
        overlap_img = overlap_img[min_r:max_r, min_c:max_c]
        overlap_img = (255*overlap_img).astype(np.uint8)

        return overlap_img

    def measure_original_mmi(self, img1, img2):
        """Measure Mattes mutation inormation between 2 unregistered images.
        """

        dst_rc = np.max([img1.shape, img2.shape], axis=1)
        padded_img_list = [None] * self.size
        for i, img in enumerate([img1, img2]):
            T = warp_tools.get_padding_matrix(img.shape, dst_rc)
            padded_img = transform.warp(img, T, preserve_range=True, output_shape=dst_rc)
            padded_img_list[i] = padded_img

        og_mmi = warp_tools.mattes_mi(padded_img_list[0], padded_img_list[1])

        return og_mmi

    def process_imgs(self, brightfield_processing_cls, brightfield_processing_kwargs,
                     if_processing_cls, if_processing_kwargs):

        f"""Process images to make them look as similar as possible

        Images will also be normalized after images are processed

        Parameters
        ----------
        brightfield_processing_cls : ImageProcesser
            ImageProcesser to pre-process brightfield images to make them look as similar as possible.
            Should return a single channel uint8 image. The default function is
            {DEFAULT_BRIGHTFIELD_CLASS.__name__} will be used for
            `img_type` = {slide_tools.IHC_NAME}. {DEFAULT_BRIGHTFIELD_CLASS.__name__}
            is located in the preprocessing module.

        brightfield_processing_kwargs : dict
            Dictionary of keyward arguments to be passed to `ihc_processing_fxn`

        if_processing_fxn : ImageProcesser
            ImageProcesser to pre-process immunofluorescent images to make them look as similar as possible.
            Should return a single channel uint8 image. If None, then {DEFAULT_FLOURESCENCE_CLASS.__name__}
            will be used for `img_type` = {slide_tools.IF_NAME}. {DEFAULT_FLOURESCENCE_CLASS.__name__} is
            located in the preprocessing module.

        if_processing_kwargs : dict
            Dictionary of keyward arguments to be passed to `if_processing_fxn`

        """

        pathlib.Path(self.processed_dir).mkdir(exist_ok=True, parents=True)
        if self.norm_method is not None:
            if self.norm_method == "histo_match":
                ref_histogram = np.zeros(256, dtype=np.int)
            else:
                all_v = [None]*self.size

        for i, slide_obj in enumerate(tqdm.tqdm(self.slide_dict.values())):
            is_ihc = slide_obj.img_type == slide_tools.IHC_NAME
            if is_ihc:
                processing_cls = brightfield_processing_cls
                processing_kwargs = brightfield_processing_kwargs

            else:
                processing_cls = if_processing_cls
                processing_kwargs = if_processing_kwargs

            levels_in_range = np.where(slide_obj.slide_dimensions_wh.max(axis=1) < self.max_processed_image_dim_px)[0]
            if len(levels_in_range) > 0:
                level = levels_in_range[0]
            else:
                level = len(slide_obj.slide_dimensions_wh) - 1
            processor = processing_cls(image=slide_obj.image, src_f=slide_obj.src_f, level=level, series=slide_obj.series)

            try:
                processed_img = processor.process_image(**processing_kwargs)
            except TypeError:
                # processor.process_image doesn't take kwargs
                processed_img = processor.process_image()

            processed_img = exposure.rescale_intensity(processed_img, out_range=(0, 255)).astype(np.uint8)
            scaling = np.min(self.max_processed_image_dim_px/np.array(processed_img.shape[0:2]))
            if scaling < 1:
                processed_img = warp_tools.rescale_img(processed_img, scaling)

            if self.create_masks:
                # Get masks #
                pathlib.Path(self.mask_dir).mkdir(exist_ok=True, parents=True)

                # Slice region from slide and process too
                mask = processor.create_mask()
                if not np.all(mask.shape == processed_img.shape[0:2]):
                    mask = warp_tools.resize_img(mask, processed_img.shape[0:2], interp_method="nearest")

                slide_obj.rigid_reg_mask = mask
                processed_img[mask == 0] = 0

                # Save image with mask drawn on top of it
                thumbnail_mask = self.create_thumbnail(mask)
                if slide_obj.img_type == slide_tools.IHC_NAME:
                    thumbnail_img = self.create_thumbnail(slide_obj.image)
                else:
                    thumbnail_img = self.create_thumbnail(processed_img)

                thumbnail_mask_outline = viz.draw_outline(thumbnail_img, thumbnail_mask)
                outline_f_out = os.path.join(self.mask_dir, f'{slide_obj.name}.png')
                warp_tools.save_img(outline_f_out, thumbnail_mask_outline)

            else:
                mask = np.full(processed_img.shape, 255, dtype=np.uint8)

            slide_obj.rigid_reg_mask = mask
            slide_obj.processed_img = processed_img

            processed_f_out = os.path.join(self.processed_dir, slide_obj.name + ".png")
            slide_obj.processed_img_f = processed_f_out
            slide_obj.processed_img_shape_rc = np.array(processed_img.shape[0:2])
            warp_tools.save_img(processed_f_out, processed_img)

            img_for_stats = processed_img.reshape(-1)

            if self.norm_method is not None:
                if self.norm_method == "histo_match":
                    img_hist, _ = np.histogram(img_for_stats, bins=256)
                    ref_histogram += img_hist
                else:
                    all_v[i] = img_for_stats.reshape(-1)

        if self.norm_method is not None:
            if self.norm_method == "histo_match":
                target_stats = ref_histogram
            else:
                all_v = np.hstack(all_v)
                target_stats = all_v

            self.normalize_images(target_stats)

    def denoise_images(self):
        for i, slide_obj in enumerate(tqdm.tqdm(self.slide_dict.values())):
            if slide_obj.rigid_reg_mask is None:
                is_ihc = slide_obj.img_type == slide_tools.IHC_NAME
                _, tissue_mask = preprocessing.create_tissue_mask(slide_obj.image, is_ihc)
                mask_bbox = warp_tools.xy2bbox(warp_tools.mask2xy(tissue_mask))
                c0, r0 = mask_bbox[:2]
                c1, r1 = mask_bbox[:2] + mask_bbox[2:]
                denoise_mask = np.zeros_like(tissue_mask)
                denoise_mask[r0:r1, c0:c1] = 255
            else:
                denoise_mask = slide_obj.rigid_reg_mask

            denoised = preprocessing.denoise_img(slide_obj.processed_img, mask=denoise_mask)
            warp_tools.save_img(slide_obj.processed_img_f, denoised)

    def normalize_images(self, target):
        """Normalize intensity values in images

        Parameters
        ----------
        target : ndarray
            Target statistics used to normalize images

        """
        print("\n==== Normalizing images\n")
        for i, slide_obj in enumerate(tqdm.tqdm(self.slide_dict.values())):
            vips_img = pyvips.Image.new_from_file(slide_obj.processed_img_f)
            img = warp_tools.vips2numpy(vips_img)
            if self.norm_method == "histo_match":
                self.target_processing_stats = target
                normed_img = preprocessing.match_histograms(img, self.target_processing_stats)
            elif self.norm_method == "img_stats":
                self.target_processing_stats = preprocessing.get_channel_stats(target)
                normed_img = preprocessing.norm_img_stats(img, self.target_processing_stats)

            normed_img = exposure.rescale_intensity(normed_img, out_range=(0, 255)).astype(np.uint8)
            slide_obj.processed_img = normed_img

            slide_obj.processed_img_shape_rc = np.array(normed_img.shape[0:2])
            warp_tools.save_img(slide_obj.processed_img_f, normed_img)

    def create_thumbnail(self, img, rescale_color=False):
        """Create thumbnail image to view results
        """
        scaling = np.min(self.thumbnail_size/np.array(img.shape[:2]))
        if scaling < 1:
            thumbnail = warp_tools.rescale_img(img, scaling)
        else:
            thumbnail = img

        if rescale_color is True:
            thumbnail = exposure.rescale_intensity(thumbnail, out_range=(0, 255)).astype(np.uint8)

        return thumbnail

    def draw_overlap_img(self, img_list):
        """Create image showing the overlap of registered images
        """

        composite_img = np.dstack(img_list)
        cmap = viz.jzazbz_cmap()
        channel_colors = viz.get_n_colors(cmap, composite_img.shape[2])
        overlap_img = viz.color_multichannel(composite_img, channel_colors,
                                             rescale_channels=True,
                                             normalize_by="channel",
                                             cspace="CAM16UCS")

        overlap_img = exposure.equalize_adapthist(overlap_img)
        overlap_img = exposure.rescale_intensity(overlap_img, out_range=(0, 255)).astype(np.uint8)

        return overlap_img

    def get_ref_img_mask(self, rigid_registrar):
        """Create mask that covers reference image

        Returns
        -------
        mask : ndarray
            Mask that covers reference image in registered images
        mask_bbox_xywh : tuple of int
            XYWH of mask in reference image

        """
        ref_slide = rigid_registrar.img_obj_dict[valtils.get_name(self.reference_img_f)]
        ref_shape_wh = ref_slide.image.shape[0:2][::-1]

        uw_mask = np.full(ref_shape_wh[::-1], 255, dtype=np.uint8)
        mask = warp_tools.warp_img(uw_mask, ref_slide.M,
                                   out_shape_rc=ref_slide.registered_shape_rc)

        reg_txy = -ref_slide.M[0:2, 2]
        mask_bbox_xywh = np.array([*reg_txy, *ref_shape_wh])

        return mask, mask_bbox_xywh

    def get_all_overlap_mask(self, rigid_registrar):
        """Create mask that covers all tissue


        Returns
        -------
        mask : ndarray
            Mask that covers reference image in registered images
        mask_bbox_xywh : tuple of int
            XYWH of mask in reference image

        """

        ref_slide = rigid_registrar.img_obj_dict[valtils.get_name(self.reference_img_f)]
        combo_mask = np.zeros(ref_slide.registered_shape_rc, dtype=int)
        for img_obj in rigid_registrar.img_obj_list:

            img_mask = self.slide_dict[img_obj.name].rigid_reg_mask
            warped_img_mask = warp_tools.warp_img(img_mask,
                                                  M=img_obj.M,
                                                  out_shape_rc=img_obj.registered_shape_rc,
                                                  interp_method="nearest")

            combo_mask[warped_img_mask > 0] += 1

        temp_mask = 255*filters.apply_hysteresis_threshold(combo_mask, 0.5, self.size-0.5).astype(np.uint8)
        mask = 255*ndimage.binary_fill_holes(temp_mask).astype(np.uint8)
        mask = preprocessing.mask2contours(mask)

        mask_bbox_xywh = warp_tools.xy2bbox(warp_tools.mask2xy(mask))

        return mask, mask_bbox_xywh



    def get_null_overlap_mask(self, rigid_registrar):
        """Create mask that covers all of the image.
        Not really a mask


        Returns
        -------
        mask : ndarray
            Mask that covers reference image in registered images
        mask_bbox_xywh : tuple of int
            XYWH of mask in reference image

        """
        reg_shape = rigid_registrar.img_obj_list[0].registered_shape_rc
        mask = np.full(reg_shape, 255, dtype=np.uint8)
        mask_bbox_xywh = np.array([0, 0, reg_shape[1], reg_shape[0]])

        return mask, mask_bbox_xywh

    def create_crop_masks(self, rigid_registrar):
        """Create masks based on rigid registration

        """
        mask_dict = {}
        mask_dict[CROP_REF] =  self.get_ref_img_mask(rigid_registrar)
        mask_dict[CROP_OVERLAP] = self.get_all_overlap_mask(rigid_registrar)
        mask_dict[CROP_NONE] = self.get_null_overlap_mask(rigid_registrar)
        self.mask_dict = mask_dict

    def get_crop_mask(self, overlap_type):
        """Get overlap mask and bounding box

        Returns
        -------
        mask : ndarray
            Mask

        mask_xywh : tuple
            XYWH for bounding box around mask

        """
        if overlap_type is None:
            overlap_type = CROP_NONE

        return self.mask_dict[overlap_type]

    def rigid_register_partial(self, tform_dict=None):
        """Perform rigid registration using provided parameters

        Still sorts images by similarity for use with non-rigid registration.

        tform_dict : dictionary
            Dictionary with rigid registration parameters. Each key is the image's file name, and
            the values are another dictionary with transformation parameters:
                M: 3x3 inverse transformation matrix. Found by determining how to align fixed to moving.
                    If M was found by determining how to align moving to fixed, then it will need to be inverted

                transformation_src_shape_rc: shape (row, col) of image used to find the rigid transformation. If
                    not provided, then it is assumed to be the shape of the level 0 slide
                transformation_dst_shape_rc: shape of registered image. If not presesnt, but a reference was provided
                    and `transformation_src_shape_rc` was not provided, this is assumed to be the shape of the reference slide

            If None, then all rigid M will be the identity matrix
        """


        # Still need to sort images #
        rigid_registrar = serial_rigid.SerialRigidRegistrar(self.processed_dir,
                                        imgs_ordered=self.imgs_ordered,
                                        reference_img_f=self.reference_img_f,
                                        name=self.name,
                                        align_to_reference=self.align_to_reference)

        feature_detector = self.rigid_reg_kwargs[FD_KEY]
        matcher = self.rigid_reg_kwargs[MATCHER_KEY]
        similarity_metric = self.rigid_reg_kwargs[SIM_METRIC_KEY]
        transformer = self.rigid_reg_kwargs[TRANSFORMER_KEY]

        print("\n======== Detecting features\n")
        rigid_registrar.generate_img_obj_list(feature_detector)


        print("\n======== Matching images\n")
        if rigid_registrar.aleady_sorted:
            rigid_registrar.match_sorted_imgs(matcher, keep_unfiltered=False)

            for i, img_obj in enumerate(rigid_registrar.img_obj_list):
                img_obj.stack_idx = i

        else:
            rigid_registrar.match_imgs(matcher, keep_unfiltered=False)

            print("\n======== Sorting images\n")
            rigid_registrar.build_metric_matrix(metric=similarity_metric)
            rigid_registrar.sort()

        rigid_registrar.distance_metric_name = matcher.metric_name
        rigid_registrar.distance_metric_type = matcher.metric_type
        rigid_registrar.get_iter_order()
        if rigid_registrar.size > 2:
            rigid_registrar.update_match_dicts_with_neighbor_filter(transformer, matcher)

        if self.reference_img_f is not None:
            ref_name = valtils.get_name(self.reference_img_f)
        else:
            ref_name = valtils.get_name(rigid_registrar.reference_img_f)
            if self.do_rigid is not False:
                msg = " ".join([f"Best to specify `{REF_IMG_KEY}` when manually providing `{TFORM_MAT_KEY}`.",
                       f"Setting this image to be {ref_name}"])

                valtils.print_warning(msg)

        # Get output shapes #
        if tform_dict is None:
            named_tform_dict = {o.name: {"M":np.eye(3)} for o in rigid_registrar.img_obj_list}
        else:
            named_tform_dict = {valtils.get_name(k):v for k, v in tform_dict.items()}

        # Get output shapes #
        rigid_ref_obj = rigid_registrar.img_obj_dict[ref_name]
        ref_slide_obj = self.slide_dict[ref_name]
        if ref_name in named_tform_dict.keys():
            ref_tforms = named_tform_dict[ref_name]
            if TFORM_SRC_SHAPE_KEY in ref_tforms:
                ref_tform_src_shape_rc = ref_tforms[TFORM_SRC_SHAPE_KEY]
            else:
                ref_tform_src_shape_rc = ref_slide_obj.slide_dimensions_wh[0][::-1]

            if TFORM_DST_SHAPE_KEY in ref_tforms:
                temp_out_shape_rc = ref_tforms[TFORM_DST_SHAPE_KEY]
            else:
                # Assume M was found by aligning to level 0 reference
                temp_out_shape_rc = ref_slide_obj.slide_dimensions_wh[0][::-1]

            ref_to_reg_sxy = (np.array(rigid_ref_obj.image.shape)/np.array(ref_tform_src_shape_rc))[::-1]
            out_rc = np.round(temp_out_shape_rc*ref_to_reg_sxy).astype(int)

        else:
            out_rc = rigid_ref_obj.image.shape

        scaled_M_dict = {}
        for img_name, img_tforms in named_tform_dict.items():
            matching_rigid_obj = rigid_registrar.img_obj_dict[img_name]
            matching_slide_obj = self.slide_dict[img_name]

            if TFORM_SRC_SHAPE_KEY in img_tforms:
                og_src_shape_rc = img_tforms[TFORM_SRC_SHAPE_KEY]
            else:
                og_src_shape_rc = matching_slide_obj.slide_dimensions_wh[0][::-1]

            temp_M = img_tforms[TFORM_MAT_KEY]
            if temp_M.shape[0] == 2:
                temp_M = np.vstack([temp_M, [0, 0, 1]])

            if TFORM_DST_SHAPE_KEY in img_tforms:
                og_dst_shape_rc = img_tforms[TFORM_DST_SHAPE_KEY]
            else:
                og_dst_shape_rc = ref_slide_obj.slide_dimensions_wh[0][::-1]

            img_corners_xy = warp_tools.get_corners_of_image(matching_rigid_obj.image.shape)[::-1]
            warped_corners = warp_tools.warp_xy(img_corners_xy, M=temp_M,
                                    transformation_src_shape_rc=og_src_shape_rc,
                                    transformation_dst_shape_rc=og_dst_shape_rc,
                                    src_shape_rc=matching_rigid_obj.image.shape,
                                    dst_shape_rc=out_rc)
            M_tform = transform.ProjectiveTransform()
            M_tform.estimate(warped_corners, img_corners_xy)
            for_reg_M = M_tform.params
            scaled_M_dict[matching_rigid_obj.name] = for_reg_M
            matching_rigid_obj.M = for_reg_M

        # Find M if not provided
        for moving_idx, fixed_idx in tqdm.tqdm(rigid_registrar.iter_order):
            img_obj = rigid_registrar.img_obj_list[moving_idx]
            if img_obj.name in scaled_M_dict:
                continue

            prev_img_obj = rigid_registrar.img_obj_list[fixed_idx]
            img_obj.fixed_obj = prev_img_obj

            print(f"finding M for {img_obj.name}, which is being aligned to {prev_img_obj.name}")

            if fixed_idx == rigid_registrar.reference_img_idx:
                prev_M = np.eye(3)

            to_prev_match_info = img_obj.match_dict[prev_img_obj]
            src_xy = to_prev_match_info.matched_kp1_xy
            dst_xy = warp_tools.warp_xy(to_prev_match_info.matched_kp2_xy, prev_M)

            transformer.estimate(dst_xy, src_xy)
            img_obj.M = transformer.params

            prev_M = img_obj.M

        # Add registered image
        for img_obj in rigid_registrar.img_obj_list:
            img_obj.M_inv = np.linalg.inv(img_obj.M)

            img_obj.registered_img = warp_tools.warp_img(img=img_obj.image,
                                                        M=img_obj.M,
                                                        out_shape_rc=out_rc)

            img_obj.registered_shape_rc = img_obj.registered_img.shape[0:2]

        return rigid_registrar

    def rigid_register(self):
        """Rigidly register slides

        Also saves thumbnails of rigidly registered images.

        Returns
        -------
        rigid_registrar : SerialRigidRegistrar
            SerialRigidRegistrar object that performed the rigid registration.

        """
        denoise = True
        if denoise:
            self.denoise_images()

        if self.do_rigid is True:
            rigid_registrar = serial_rigid.register_images(self.processed_dir,
                                                        align_to_reference=self.align_to_reference,
                                                        **self.rigid_reg_kwargs)
        else:
            if isinstance(self.do_rigid, dict):
                # User provided transforms
                rigid_tforms = self.do_rigid
            elif self.do_rigid is False:
                # Skip rigid registration
                rigid_tforms = None

            rigid_registrar = self.rigid_register_partial(tform_dict=rigid_tforms)

        self.end_rigid_time = time()
        self.rigid_registrar = rigid_registrar
        if rigid_registrar is False:
            msg = "Rigid registration failed"
            valtils.print_warning(msg)

            return False

        # Draw and save overlap image #
        self.aligned_img_shape_rc = rigid_registrar.img_obj_list[0].registered_shape_rc
        self.reference_img_idx = rigid_registrar.reference_img_idx
        ref_slide = self.slide_dict[valtils.get_name(rigid_registrar.reference_img_f)]
        self.reference_img_f = ref_slide.src_f

        self.create_crop_masks(rigid_registrar)
        overlap_mask, overlap_mask_bbox_xywh = self.get_crop_mask(self.crop)

        overlap_mask_bbox_xywh = overlap_mask_bbox_xywh.astype(int)


        # Create original overlap image #
        self.original_overlap_img = self.create_original_composite_img(rigid_registrar)

        pathlib.Path(self.overlap_dir).mkdir(exist_ok=True, parents=True)
        original_overlap_img_fout = os.path.join(self.overlap_dir, self.name + "_original_overlap.png")
        warp_tools.save_img(original_overlap_img_fout,  self.original_overlap_img, thumbnail_size=self.thumbnail_size)

        pathlib.Path(self.reg_dst_dir).mkdir(exist_ok=  True, parents=  True)
        # Update attributes in slide_obj #
        n_digits = len(str(rigid_registrar.size))
        for slide_reg_obj in rigid_registrar.img_obj_list:
            slide_obj = self.slide_dict[slide_reg_obj.name]
            slide_obj.M = slide_reg_obj.M
            slide_obj.stack_idx = slide_reg_obj.stack_idx
            slide_obj.reg_img_shape_rc = slide_reg_obj.registered_img.shape
            slide_obj.rigid_reg_img_f = os.path.join(self.reg_dst_dir,
                                                     str.zfill(str(slide_obj.stack_idx), n_digits) + "_" + slide_obj.name + ".png")
            if slide_obj.image.ndim > 2:
                # Won't know if single channel image is processed RGB (bight bg) or IF channel (dark bg)
                slide_obj.get_bg_color_px_pos()

            if slide_reg_obj.stack_idx == self.reference_img_idx:
                continue

            fixed_slide = self.slide_dict[slide_reg_obj.fixed_obj.name]
            slide_obj.fixed_slide = fixed_slide

            match_dict = slide_reg_obj.match_dict[slide_reg_obj.fixed_obj]
            slide_obj.xy_matched_to_prev = match_dict.matched_kp1_xy
            slide_obj.xy_in_prev = match_dict.matched_kp2_xy

            # Get points in overlap box #
            prev_kp_warped_for_bbox_test = warp_tools.warp_xy(slide_obj.xy_in_prev, M=slide_obj.M)
            _, prev_kp_in_bbox_idx = \
                warp_tools.get_pts_in_bbox(prev_kp_warped_for_bbox_test, overlap_mask_bbox_xywh)

            current_kp_warped_for_bbox_test = \
                warp_tools.warp_xy(slide_obj.xy_matched_to_prev, M=slide_obj.M)

            _, current_kp_in_bbox_idx = \
                warp_tools.get_pts_in_bbox(current_kp_warped_for_bbox_test, overlap_mask_bbox_xywh)

            matched_kp_in_bbox = np.intersect1d(prev_kp_in_bbox_idx, current_kp_in_bbox_idx)
            slide_obj.xy_matched_to_prev_in_bbox =  slide_obj.xy_matched_to_prev[matched_kp_in_bbox]
            slide_obj.xy_in_prev_in_bbox = slide_obj.xy_in_prev[matched_kp_in_bbox]


        if denoise:
            # Processed image may have been denoised for rigid registration. Replace with unblurred image
            for img_obj in rigid_registrar.img_obj_list:
                matching_slide = self.slide_dict[img_obj.name]
                reg_img = matching_slide.warp_img(matching_slide.processed_img, non_rigid=False, crop=False)
                img_obj.registered_img = reg_img
                img_obj.image = matching_slide.processed_img

        rigid_img_list = [img_obj.registered_img for img_obj in rigid_registrar.img_obj_list]
        self.rigid_overlap_img = self.draw_overlap_img(rigid_img_list)
        self.rigid_overlap_img = warp_tools.crop_img(self.rigid_overlap_img, overlap_mask_bbox_xywh)

        rigid_overlap_img_fout = os.path.join(self.overlap_dir, self.name + "_rigid_overlap.png")
        warp_tools.save_img(rigid_overlap_img_fout, self.rigid_overlap_img, thumbnail_size=self.thumbnail_size)

        # Overwrite black and white processed images #
        for slide_name, slide_obj in self.slide_dict.items():
            slide_reg_obj = rigid_registrar.img_obj_dict[slide_name]
            if not slide_obj.is_rgb:
                img_to_warp = slide_reg_obj.image
            else:
                img_to_warp = slide_obj.image

            warped_img = slide_obj.warp_img(img_to_warp, non_rigid=False, crop=self.crop)
            warp_tools.save_img(slide_obj.rigid_reg_img_f, warped_img.astype(np.uint8), thumbnail_size=self.thumbnail_size)

            # Replace processed image with a thumbnail #
            warp_tools.save_img(slide_obj.processed_img_f, slide_reg_obj.image, thumbnail_size=self.thumbnail_size)

        return rigid_registrar

    def create_non_rigid_reg_mask(self):
        """
        Get mask for non-rigid registration
        """
        any_rigid_reg_masks = np.any([slide_obj.rigid_reg_mask is not None for slide_obj in self.slide_dict.values()])
        if any_rigid_reg_masks:
            non_rigid_mask = self._create_non_rigid_reg_mask_from_rigid_masks()
        else:
            non_rigid_mask = self._create_non_rigid_reg_mask_from_bbox()

        for slide_obj in self.slide_dict.values():
            slide_obj.non_rigid_reg_mask = non_rigid_mask

        # Save thumbnail of mask
        ref_slide = self.get_ref_slide()
        if ref_slide.img_type == slide_tools.IHC_NAME:
            warped_ref_img = ref_slide.warp_img(non_rigid=False, crop=CROP_REF)
        else:
            warped_ref_img = ref_slide.warp_img(ref_slide.processed_img, non_rigid=False, crop=CROP_REF)

        pathlib.Path(self.mask_dir).mkdir(exist_ok=True, parents=True)
        thumbnail_img = self.create_thumbnail(warped_ref_img)

        draw_mask = warp_tools.resize_img(non_rigid_mask, ref_slide.reg_img_shape_rc, interp_method="nearest")
        _, overlap_mask_bbox_xywh = self.get_crop_mask(CROP_REF)
        draw_mask = warp_tools.crop_img(draw_mask, overlap_mask_bbox_xywh.astype(int))
        thumbnail_mask = self.create_thumbnail(draw_mask)

        thumbnail_mask_outline = viz.draw_outline(thumbnail_img, thumbnail_mask)
        outline_f_out = os.path.join(self.mask_dir, f'{self.name}_non_rigid_mask.png')
        warp_tools.save_img(outline_f_out, thumbnail_mask_outline)

    def _create_non_rigid_reg_mask_from_bbox(self):
        """Mask will be bounding box of image overlaps

        """
        ref_slide = self.get_ref_slide()
        combo_mask = np.zeros(ref_slide.reg_img_shape_rc, dtype=int)
        for slide_obj in self.slide_dict.values():
            img_bbox = np.full(slide_obj.processed_img_shape_rc, 255, dtype=np.uint8)
            rigid_mask = slide_obj.warp_img(img_bbox, non_rigid=False, crop=False, interp_method="nearest")
            combo_mask[rigid_mask > 0] += 1

        overlap_mask = (combo_mask == self.size).astype(np.uint8)
        overlap_bbox = warp_tools.xy2bbox(warp_tools.mask2xy(overlap_mask))
        c0, r0 = overlap_bbox[:2]
        c1, r1 = overlap_bbox[:2] + overlap_bbox[2:]

        non_rigid_mask = np.zeros_like(overlap_mask)
        non_rigid_mask[r0:r1, c0:c1] = 255

        return non_rigid_mask


    def _create_non_rigid_reg_mask_from_rigid_masks(self):
        """
        Get mask that will cover all tissue. Use hysteresis thresholding to ignore
        masked regions found in only 1 image.

        """
        
        combo_mask = np.zeros(self.aligned_img_shape_rc, dtype=int)
        for i, slide_obj in enumerate(self.slide_dict.values()):
            rigid_mask = slide_obj.warp_img(slide_obj.rigid_reg_mask, non_rigid=False, crop=False, interp_method="nearest")
            combo_mask[rigid_mask > 0] += 1

        temp_non_rigid_mask = 255*filters.apply_hysteresis_threshold(combo_mask, 0.5, self.size-0.5).astype(np.uint8)

        # Draw convex hull around each region
        non_rigid_mask = 255*ndimage.binary_fill_holes(temp_non_rigid_mask).astype(np.uint8)
        non_rigid_mask = preprocessing.mask2contours(non_rigid_mask)

        return non_rigid_mask

    def pad_displacement(self, dxdy, out_shape_rc, bbox_xywh):

        is_array = not isinstance(dxdy, pyvips.Image)
        if is_array:
            vips_dxdy = warp_tools.numpy2vips(np.dstack(dxdy))
        else:
            vips_dxdy = dxdy

        full_dxdy = pyvips.Image.black(out_shape_rc[1], out_shape_rc[0], bands=2).cast("float")
        full_dxdy = full_dxdy.insert(vips_dxdy, *bbox_xywh[0:2])

        if is_array:
            full_dxdy = warp_tools.vips2numpy(full_dxdy)
            full_dxdy = np.array([full_dxdy[..., 0], full_dxdy[..., 1]])

        return full_dxdy

    def prep_images_for_large_non_rigid_registration(self, max_img_dim,
                                                        brightfield_processing_cls,
                                                        brightfield_processing_kwargs,
                                                        if_processing_cls,
                                                        if_processing_kwargs,
                                                        updating_non_rigid=False,
                                                        mask=None):
        """Scale and process images for non-rigid registration using larger images

        Parameters
        ----------
        max_img_dim : int, optional
            Maximum size of image to be used for non-rigid registration. If None, the whole image
            will be used  for non-rigid registration

        brightfield_processing_fxn : callable
            Function to pre-process brightfield images to make them look as similar as possible.
            Should return a single channel uint8 image.

        brightfield_processing_kwargs : dict
            Dictionary of keyward arguments to be passed to `ihc_processing_fxn`

        if_processing_fxn : callable
            Function to pre-process immunofluorescent images to make them look as similar as possible.
            Should return a single channel uint8 image.

        if_processing_kwargs : dict
            Dictionary of keyward arguments to be passed to `if_processing_fxn`

        updating_non_rigid : bool, optional
            If `True`, the slide's current non-rigid registration will be applied
            The new displacements found using these larger images can therefore be used
            to update existing dxdy. If `False`, only the rigid transform will be applied,
            so this will be the first non-rigid transformation.

        mask : ndarray, optional
            Binary image indicating where to perform the non-rigid registration. Should be
            based off an already registered image.

        Returns
        -------
        img_dict : dictionary
            Dictionary that can be passed to a non-rigid registrar

        max_img_dim : int
            Maximum size of image to do non-rigid registration on. May be different
            if the requested size was too big

        scaled_non_rigid_mask : ndarray
            Scaled mask to use for non-rigid registration

        full_out_shape : ndarray of int
            Shape (row, col) of the warped images, without cropping

        mask_bbox_xywh : list
            Bounding box of `mask`. If `mask` is None, then so will `mask_bbox_xywh`

        """

        warp_full_img = max_img_dim is None
        if not warp_full_img:
            all_max_dims = [np.any(np.max(slide_obj.slide_dimensions_wh, axis=1) >= max_img_dim) for slide_obj in self.slide_dict.values()]
            if not np.all(all_max_dims):
                img_maxes = [np.max(slide_obj.slide_dimensions_wh, axis=1)[0] for slide_obj in self.slide_dict.values()]
                smallest_img_max = np.min(img_maxes)
                msg = (f"Requested size of images for non-rigid registration was {max_img_dim}. "
                    f"However, not all images are this large. Setting `max_non_rigid_registartion_dim_px` to "
                    f"{smallest_img_max}, which is the largest dimension of the smallest image")
                valtils.print_warning(msg)
                max_img_dim = smallest_img_max

        ref_slide = self.get_ref_slide()

        max_s = np.min(ref_slide.slide_dimensions_wh[0]/np.array(ref_slide.processed_img_shape_rc[::-1]))
        if mask is None:
            if warp_full_img:
                s = max_s
            else:
                s = np.min(max_img_dim/np.array(ref_slide.processed_img_shape_rc))
        else:
            # Determine how big image would have to be to get mask with maxmimum dimension = max_img_dim
            if isinstance(mask, pyvips.Image):
                mask_shape_rc = np.array((mask.height, mask.width))
            else:
                mask_shape_rc = np.array(mask.shape[0:2])

            to_reg_mask_sxy = (mask_shape_rc/np.array(ref_slide.reg_img_shape_rc))[::-1]
            if not np.all(to_reg_mask_sxy == 1):
                # Resize just in case it's huge. Only need bounding box
                reg_size_mask = warp_tools.resize_img(mask, ref_slide.reg_img_shape_rc, interp_method="nearest")
            else:
                reg_size_mask = mask
            reg_size_mask_xy = warp_tools.mask2xy(reg_size_mask)
            to_reg_mask_bbox_xywh = list(warp_tools.xy2bbox(reg_size_mask_xy))
            to_reg_mask_wh = np.round(to_reg_mask_bbox_xywh[2:]).astype(int)
            if warp_full_img:
                s = max_s
            else:
                s = np.min(max_img_dim/np.array(to_reg_mask_wh))

        if s < max_s:
            full_out_shape = self.get_aligned_slide_shape(s)
        else:
            full_out_shape = self.get_aligned_slide_shape(0)

        if mask is None:
            out_shape = full_out_shape
            mask_bbox_xywh = None
        else:
            # If masking, the area will be smaller. Get bounding box
            mask_sxy = (full_out_shape/mask_shape_rc)[::-1]
            mask_bbox_xywh = list(warp_tools.xy2bbox(mask_sxy*reg_size_mask_xy))
            mask_bbox_xywh[2:] = np.round(mask_bbox_xywh[2:]).astype(int)
            out_shape = mask_bbox_xywh[2:][::-1]

            if not isinstance(mask, pyvips.Image):
                vips_micro_reg_mask = warp_tools.numpy2vips(mask)
            else:
                vips_micro_reg_mask = mask
            vips_micro_reg_mask = warp_tools.resize_img(vips_micro_reg_mask, full_out_shape, interp_method="nearest")
            vips_micro_reg_mask = warp_tools.crop_img(img=vips_micro_reg_mask, xywh=mask_bbox_xywh)

        use_tiler = False
        if ref_slide.reader.metadata.bf_datatype is not None:
            np_dtype = slide_tools.BF_FORMAT_NUMPY_DTYPE[ref_slide.reader.metadata.bf_datatype]
        else:
            # Assuming images not read by bio-formats are RGB read using from openslide or png, jpeg, etc...
            np_dtype = "uint8"

        displacement_gb = self.size*warp_tools.calc_memory_size_gb(full_out_shape, 2, "float32")
        processed_img_gb = self.size*warp_tools.calc_memory_size_gb(out_shape, 1, "uint8")
        img_gb = self.size*warp_tools.calc_memory_size_gb(out_shape, ref_slide.reader.metadata.n_channels, np_dtype)

        # Size of full displacement fields, all larger processed images, and an image that will be processed
        estimated_gb = img_gb + displacement_gb + processed_img_gb

        if estimated_gb > TILER_THRESH_GB:
            # Avoid having huge displacement fields saved in registrar. Would make it difficult to open
            use_tiler = True

        scaled_warped_img_list = [None] * self.size
        scaled_mask_list = [None] * self.size
        img_names_list = [None] * self.size
        img_f_list = [None] * self.size

        print("\n======== Preparing images for non-rigid registraration\n")
        for slide_obj in tqdm.tqdm(self.slide_dict.values()):

            # Get image to warp. Likely a larger image scaled down to specified shape #
            src_img_shape_rc, src_M = warp_tools.get_src_img_shape_and_M(transformation_src_shape_rc=slide_obj.processed_img_shape_rc,
                                                                            transformation_dst_shape_rc=slide_obj.reg_img_shape_rc,
                                                                            dst_shape_rc=full_out_shape,
                                                                            M=slide_obj.M)

            if max_img_dim is not None:
                if mask is not None:
                    closest_img_levels = np.where(np.max(slide_obj.slide_dimensions_wh, axis=1) < np.max(src_img_shape_rc))[0]
                    if len(closest_img_levels) > 0:
                        closest_img_level = closest_img_levels[0] - 1
                    else:
                        closest_img_level = len(slide_obj.slide_dimensions_wh) - 1
            else:
                closest_img_level = 0

            vips_level_img = slide_obj.slide2vips(closest_img_level)
            img_to_warp = warp_tools.resize_img(vips_level_img, src_img_shape_rc)

            if updating_non_rigid:
                dxdy = slide_obj.bk_dxdy
            else:
                dxdy = None

            # Get mask
            temp_processing_mask = slide_obj.warp_img(slide_obj.rigid_reg_mask, non_rigid=dxdy is not None, crop=False, interp_method="nearest")
            temp_processing_mask = warp_tools.numpy2vips(temp_processing_mask)
            slide_mask = warp_tools.resize_img(temp_processing_mask, full_out_shape, interp_method="nearest")
            if mask_bbox_xywh is not None:
                slide_mask = warp_tools.crop_img(slide_mask, mask_bbox_xywh)

            if not use_tiler:
                # Process image using same method for rigid registration #
                unprocessed_warped_img = warp_tools.warp_img(img=img_to_warp, M=slide_obj.M,
                    bk_dxdy=dxdy,
                    transformation_src_shape_rc=slide_obj.processed_img_shape_rc,
                    transformation_dst_shape_rc=slide_obj.reg_img_shape_rc,
                    out_shape_rc=full_out_shape,
                    bbox_xywh=mask_bbox_xywh,
                    bg_color=slide_obj.bg_color)

                unprocessed_warped_img = warp_tools.vips2numpy(unprocessed_warped_img)

                temp_processing_mask = pyvips.Image.black(img_to_warp.width, img_to_warp.height).invert()
                processing_mask = warp_tools.warp_img(img=temp_processing_mask, M=slide_obj.M,
                    bk_dxdy=dxdy,
                    transformation_src_shape_rc=slide_obj.processed_img_shape_rc,
                    transformation_dst_shape_rc=slide_obj.reg_img_shape_rc,
                    out_shape_rc=full_out_shape,
                    bbox_xywh=mask_bbox_xywh,
                    interp_method="nearest")

                if slide_obj.img_type == slide_tools.IHC_NAME:
                    processing_cls = brightfield_processing_cls
                    processing_kwargs = brightfield_processing_kwargs
                else:
                    processing_cls = if_processing_cls
                    processing_kwargs = if_processing_kwargs

                processor = processing_cls(image=unprocessed_warped_img, src_f=slide_obj.src_f, level=closest_img_level, series=slide_obj.series)

                try:
                    processed_img = processor.process_image(**processing_kwargs)
                except TypeError:
                    # processor.process_image doesn't take kwargs
                    processed_img = processor.process_image()
                processed_img = exposure.rescale_intensity(processed_img, out_range=(0, 255)).astype(np.uint8)

                np_mask = warp_tools.vips2numpy(slide_mask)
                processed_img[np_mask==0] = 0

                # Normalize images using stats collected for rigid registration #
                warped_img = preprocessing.norm_img_stats(processed_img, self.target_processing_stats, mask=slide_mask)
                warped_img = exposure.rescale_intensity(warped_img, out_range=(0, 255)).astype(np.uint8)

            else:
                if not warp_full_img:
                    warped_img = warp_tools.warp_img(img=img_to_warp, M=slide_obj.M,
                                bk_dxdy=dxdy,
                                transformation_src_shape_rc=slide_obj.processed_img_shape_rc,
                                transformation_dst_shape_rc=slide_obj.reg_img_shape_rc,
                                out_shape_rc=full_out_shape,
                                bbox_xywh=mask_bbox_xywh)
                else:
                    warped_img = slide_obj.warp_slide(0, non_rigid=updating_non_rigid, crop=mask_bbox_xywh)

            # Get mask #
            if mask is not None:
                slide_mask = (vips_micro_reg_mask==0).ifthenelse(0, slide_mask)

            # Update lists
            img_f_list[slide_obj.stack_idx] = slide_obj.src_f
            img_names_list[slide_obj.stack_idx] = slide_obj.name
            scaled_warped_img_list[slide_obj.stack_idx] = warped_img
            scaled_mask_list[slide_obj.stack_idx] = processing_mask


        img_dict = {serial_non_rigid.IMG_LIST_KEY: scaled_warped_img_list,
                    serial_non_rigid.IMG_F_LIST_KEY: img_f_list,
                    serial_non_rigid.MASK_LIST_KEY: scaled_mask_list,
                    serial_non_rigid.IMG_NAME_KEY: img_names_list
                    }

        if ref_slide.non_rigid_reg_mask is not None:
            vips_nr_mask = warp_tools.numpy2vips(ref_slide.non_rigid_reg_mask)
            scaled_non_rigid_mask = warp_tools.resize_img(vips_nr_mask, full_out_shape, interp_method="nearest")
            if mask is not None:
                scaled_non_rigid_mask = scaled_non_rigid_mask.extract_area(*mask_bbox_xywh)
                scaled_non_rigid_mask = (vips_micro_reg_mask == 0).ifthenelse(0, scaled_non_rigid_mask)
            if not use_tiler:
                scaled_non_rigid_mask = warp_tools.vips2numpy(scaled_non_rigid_mask)
        else:
            scaled_non_rigid_mask = None

        if mask is not None:
            final_max_img_dim = np.max(mask_bbox_xywh[2:])
        else:
            final_max_img_dim = max_img_dim

        return img_dict, final_max_img_dim, scaled_non_rigid_mask, full_out_shape, mask_bbox_xywh


    def non_rigid_register(self, rigid_registrar,
        brightfield_processing_cls, brightfield_processing_kwargs,
        if_processing_cls, if_processing_kwargs):

        """Non-rigidly register slides

        Non-rigidly register slides after performing rigid registration.
        Also saves thumbnails of non-rigidly registered images and deformation
        fields.

        Parameters
        ----------
        rigid_registrar : SerialRigidRegistrar
            SerialRigidRegistrar object that performed the rigid registration.

        Returns
        -------
        non_rigid_registrar : SerialNonRigidRegistrar
            SerialNonRigidRegistrar object that performed serial
            non-rigid registration.

        """

        ref_slide = self.get_ref_slide()

        self.create_non_rigid_reg_mask()
        non_rigid_reg_mask = ref_slide.non_rigid_reg_mask
        cropped_mask_shape_rc = warp_tools.xy2bbox(warp_tools.mask2xy(non_rigid_reg_mask))[2:][::-1]

        nr_on_scaled_img = self.max_processed_image_dim_px != self.max_non_rigid_registartion_dim_px or \
            (non_rigid_reg_mask is not None and np.any(cropped_mask_shape_rc != ref_slide.reg_img_shape_rc))

        if nr_on_scaled_img:

            # Use higher resolution and/or roi for non-rigid
            nr_reg_src, max_img_dim, non_rigid_reg_mask, full_out_shape_rc, mask_bbox_xywh = \
                self.prep_images_for_large_non_rigid_registration(max_img_dim=self.max_non_rigid_registartion_dim_px,
                                                                  brightfield_processing_cls=brightfield_processing_cls,
                                                                  brightfield_processing_kwargs=brightfield_processing_kwargs,
                                                                  if_processing_cls=if_processing_cls,
                                                                  if_processing_kwargs=if_processing_kwargs,
                                                                  mask=non_rigid_reg_mask)

            self._non_rigid_bbox = mask_bbox_xywh
            self.max_non_rigid_registartion_dim_px = max_img_dim
        else:
            nr_reg_src = rigid_registrar
            full_out_shape_rc = ref_slide.reg_img_shape_rc


        self._full_displacement_shape_rc = full_out_shape_rc
        non_rigid_registrar = serial_non_rigid.register_images(src=nr_reg_src,
                                                               align_to_reference=self.align_to_reference,
                                                               **self.non_rigid_reg_kwargs)
        self.end_non_rigid_time = time()

        for d in  [self.non_rigid_dst_dir, self.deformation_field_dir]:
            pathlib.Path(d).mkdir(exist_ok=True, parents=True)
        self.non_rigid_registrar = non_rigid_registrar


        # Clean up displacements and expand if mask was used
        for nr_name, nr_obj in non_rigid_registrar.non_rigid_obj_dict.items():
            if nr_on_scaled_img:
                # If a mask was used, the displacement fields will be smaller
                # So need to insert them in the full image
                bk_dxdy = self.pad_displacement(nr_obj.bk_dxdy, full_out_shape_rc, mask_bbox_xywh)
                fwd_dxdy = self.pad_displacement(nr_obj.fwd_dxdy, full_out_shape_rc, mask_bbox_xywh)
            else:
                bk_dxdy = nr_obj.bk_dxdy
                fwd_dxdy = nr_obj.fwd_dxdy

            nr_obj.bk_dxdy = bk_dxdy
            nr_obj.fwd_dxdy = fwd_dxdy

        # Draw overlap image #
        overlap_mask, overlap_mask_bbox_xywh = self.get_crop_mask(self.crop)
        overlap_mask_bbox_xywh = overlap_mask_bbox_xywh.astype(int)

        if not nr_on_scaled_img:
            non_rigid_img_list = [nr_img_obj.registered_img for nr_img_obj in non_rigid_registrar.non_rigid_obj_list]
        else:
            non_rigid_img_list = [warp_tools.warp_img(img=o.image,
                                                    M=o.M,
                                                    bk_dxdy= non_rigid_registrar.non_rigid_obj_dict[o.name].bk_dxdy,
                                                    out_shape_rc=o.registered_img.shape[0:2],
                                                    transformation_src_shape_rc=o.image.shape[0:2],
                                                    transformation_dst_shape_rc=o.registered_img.shape[0:2])
                                                for o in rigid_registrar.img_obj_list]

        self.non_rigid_overlap_img  = self.draw_overlap_img(non_rigid_img_list)
        self.non_rigid_overlap_img = warp_tools.crop_img(self.non_rigid_overlap_img, overlap_mask_bbox_xywh)

        overlap_img_fout = os.path.join(self.overlap_dir, self.name + "_non_rigid_overlap.png")
        warp_tools.save_img(overlap_img_fout, self.non_rigid_overlap_img, thumbnail_size=self.thumbnail_size)

        n_digits = len(str(self.size))
        for slide_name, slide_obj in self.slide_dict.items():
            img_save_id = str.zfill(str(slide_obj.stack_idx), n_digits)
            slide_nr_reg_obj = non_rigid_registrar.non_rigid_obj_dict[slide_name]
            slide_obj.bk_dxdy = slide_nr_reg_obj.bk_dxdy
            slide_obj.fwd_dxdy = slide_nr_reg_obj.fwd_dxdy
            slide_obj.nr_rigid_reg_img_f = os.path.join(self.non_rigid_dst_dir, img_save_id + "_" + slide_obj.name + ".png")

            if not slide_obj.is_rgb:
                img_to_warp = rigid_registrar.img_obj_dict[slide_name].image
            else:
                img_to_warp = slide_obj.image

            warped_img = slide_obj.warp_img(img_to_warp, non_rigid=True, crop=self.crop)
            warp_tools.save_img(slide_obj.nr_rigid_reg_img_f, warped_img, thumbnail_size=self.thumbnail_size)

            # Draw displacements on image actually used in non-rigid. Might be higher resolution
            draw_dxdy = np.dstack(slide_nr_reg_obj.bk_dxdy)
            if nr_on_scaled_img:
                draw_dxdy = warp_tools.crop_img(draw_dxdy, self._non_rigid_bbox)

            thumbnail_scaling = np.min(self.thumbnail_size/np.array(draw_dxdy.shape[0:2]))
            thumbnail_bk_dxdy = self.create_thumbnail(draw_dxdy)
            thumbnail_bk_dxdy *= thumbnail_scaling

            draw_img = transform.resize(slide_nr_reg_obj.registered_img,
                            thumbnail_bk_dxdy[..., 0].shape,
                            preserve_range=True).astype(slide_nr_reg_obj.image.dtype)

            draw_img = exposure.rescale_intensity(draw_img, out_range=(0, 255))

            if draw_img.ndim == 2:
                draw_img = np.dstack([draw_img] * 3)


            thumbanil_deform_grid = viz.color_displacement_tri_grid(bk_dx=thumbnail_bk_dxdy[..., 0],
                                                                    bk_dy=thumbnail_bk_dxdy[..., 1],
                                                                    img=draw_img,
                                                                    n_grid_pts=25)

            deform_img_f = os.path.join(self.deformation_field_dir, img_save_id + "_" + slide_obj.name + ".png")
            warp_tools.save_img(deform_img_f, thumbanil_deform_grid, thumbnail_size=self.thumbnail_size)

        return non_rigid_registrar

    def measure_error(self):
        """Measure registration error

        Error is measured as the distance between matched features
        after registration.

        Returns
        -------
        summary_df : Dataframe
            `summary_df` contains various information about the registration.

            The "from" column is the name of the image, while the "to" column
            name of the image it was aligned to. "from" is analagous to "moving"
            or "current", while "to" is analgous to "fixed" or "previous".

            Columns begining with "original" refer to error measurements of the
            unregistered images. Those beginning with "rigid" or "non_rigid" refer
            to measurements related to rigid or non-rigid registration, respectively.

            Columns beginning with "mean" are averages of error measurements. In
            the case of errors based on feature distances (i.e. those ending in "D"),
            the mean is weighted by the number of feature matches between "from" and "to".

            Columns endining in "D" indicate the median distance between matched
            features in "from" and "to".

            Columns ending in "rTRE" indicate the target registration error between
            "from" and "to".

            Columns ending in "mattesMI" contain measurements of the Mattes mutual
            information between "from" and "to".

            "processed_img_shape" indicates the shape (row, column) of the processed
            image actually used to conduct the registration

            "shape" is the shape of the slide at full resolution

            "aligned_shape" is the shape of the registered full resolution slide

            "physical_units" are the names of the pixels physcial unit, e.g. u'\u00B5m'

            "resolution" is the physical unit per pixel

            "name" is the name assigned to the Valis instance

            "rigid_time_minutes" is the total number of minutes it took
            to convert the images and then rigidly align them.

            "non_rigid_time_minutes" is the total number of minutes it took
            to convert the images, and then perform rigid -> non-rigid registration.

        """

        path_list = [None] * (self.size)
        all_og_d = [None] * (self.size)
        all_og_tre = [None] * (self.size)

        all_rigid_d = [None] * (self.size)
        all_rigid_tre = [None] * (self.size)

        all_nr_d = [None] * (self.size)
        all_nr_tre = [None] * (self.size)

        all_n = [None] * (self.size)
        from_list = [None] * (self.size)
        to_list = [None] * (self.size)
        shape_list = [None] * (self.size)
        processed_img_shape_list = [None] * (self.size)
        unit_list = [None] * (self.size)
        resolution_list = [None] * (self.size)

        slide_obj_list = list(self.slide_dict.values())
        outshape = slide_obj_list[0].aligned_slide_shape_rc

        ref_slide = self.get_ref_slide()
        ref_diagonal = np.sqrt(np.sum(np.power(ref_slide.processed_img_shape_rc, 2)))

        for slide_obj in tqdm.tqdm(self.slide_dict.values()):
            i = slide_obj.stack_idx
            slide_name = slide_obj.name

            shape_list[i] = tuple(slide_obj.slide_shape_rc)
            processed_img_shape_list[i] = tuple(slide_obj.processed_img_shape_rc)
            unit_list[i] = slide_obj.units
            resolution_list[i] = slide_obj.resolution
            from_list[i] = slide_name
            path_list[i] = slide_obj.src_f

            if slide_obj.name == ref_slide.name:
                continue

            prev_slide_obj = slide_obj.fixed_slide
            to_list[i] = prev_slide_obj.name

            img_T = warp_tools.get_padding_matrix(slide_obj.processed_img_shape_rc,
                                                  slide_obj.reg_img_shape_rc)

            prev_T = warp_tools.get_padding_matrix(prev_slide_obj.processed_img_shape_rc,
                                                   prev_slide_obj.reg_img_shape_rc)


            prev_kp_in_slide = prev_slide_obj.warp_xy(slide_obj.xy_in_prev,
                                                     M=prev_T,
                                                     pt_level= prev_slide_obj.processed_img_shape_rc,
                                                     non_rigid=False)

            current_kp_in_slide = slide_obj.warp_xy(slide_obj.xy_matched_to_prev,
                                                    M=img_T,
                                                    pt_level= slide_obj.processed_img_shape_rc,
                                                    non_rigid=False)

            og_d = warp_tools.calc_d(prev_kp_in_slide, current_kp_in_slide)

            og_rtre = og_d/ref_diagonal
            median_og_tre = np.median(og_rtre)
            og_d *= slide_obj.resolution
            median_d_og = np.median(og_d)

            all_og_d[i] = median_d_og
            all_og_tre[i] = median_og_tre


            prev_warped_rigid = prev_slide_obj.warp_xy(slide_obj.xy_in_prev,
                                                       M=prev_slide_obj.M,
                                                       pt_level= prev_slide_obj.processed_img_shape_rc,
                                                       non_rigid=False)

            current_warped_rigid = slide_obj.warp_xy(slide_obj.xy_matched_to_prev,
                                                     M=slide_obj.M,
                                                     pt_level= slide_obj.processed_img_shape_rc,
                                                     non_rigid=False)


            rigid_d = warp_tools.calc_d(prev_warped_rigid, current_warped_rigid)
            rtre = rigid_d/ref_diagonal
            median_rigid_tre = np.median(rtre)
            rigid_d *= slide_obj.resolution
            median_d_rigid = np.median(rigid_d)

            all_rigid_d[i] = median_d_rigid
            all_n[i] = len(rigid_d)
            all_rigid_tre[i] = median_rigid_tre

            if slide_obj.bk_dxdy is not None:


                prev_warped_nr = prev_slide_obj.warp_xy(slide_obj.xy_in_prev,
                                                        M=prev_slide_obj.M,
                                                        pt_level= prev_slide_obj.processed_img_shape_rc,
                                                        non_rigid=True)

                current_warped_nr = slide_obj.warp_xy(slide_obj.xy_matched_to_prev,
                                                      M=slide_obj.M,
                                                      pt_level= slide_obj.processed_img_shape_rc,
                                                      non_rigid=True)

                nr_d =  warp_tools.calc_d(prev_warped_nr, current_warped_nr)
                nrtre = nr_d/ref_diagonal
                mean_nr_tre = np.median(nrtre)

                nr_d *= slide_obj.resolution
                median_d_nr = np.median(nr_d)
                all_nr_d[i] = median_d_nr
                all_nr_tre[i] = mean_nr_tre


        non_ref_idx = list(range(self.size))
        non_ref_idx.remove(self.reference_img_idx)

        non_ref_weights = np.array(all_n)[non_ref_idx]
        mean_og_d = np.average(np.array(all_og_d)[non_ref_idx], weights=non_ref_weights)
        median_og_tre = np.average(np.array(all_og_tre)[non_ref_idx], weights=non_ref_weights)

        mean_rigid_d = np.average(np.array(all_rigid_d)[non_ref_idx], weights=non_ref_weights)
        median_rigid_tre = np.average(np.array(all_rigid_tre)[non_ref_idx], weights=non_ref_weights)

        rigid_min = (self.end_rigid_time - self.start_time)/60

        self.summary_df = pd.DataFrame({
            "filename": path_list,
            "from":from_list,
            "to": to_list,
            "original_D": all_og_d,
            "original_rTRE": all_og_tre,
            "rigid_D": all_rigid_d,
            "rigid_rTRE": all_rigid_tre,
            "non_rigid_D": all_nr_d,
            "non_rigid_rTRE": all_rigid_tre,
            "processed_img_shape": processed_img_shape_list,
            "shape": shape_list,
            "aligned_shape": [tuple(outshape)]*self.size,
            "mean_original_D": [mean_og_d]*self.size,
            "mean_rigid_D": [mean_rigid_d]*self.size,
            "physical_units":unit_list,
            "resolution":resolution_list,
            "name": [self.name]*self.size,
            "rigid_time_minutes" : [rigid_min]*self.size
        })

        if slide_obj.bk_dxdy is not None:
            mean_nr_d = np.average(np.array(all_nr_d)[non_ref_idx], weights=non_ref_weights)
            mean_nr_tre = np.average(np.array(all_nr_tre)[non_ref_idx], weights=non_ref_weights)
            non_rigid_min = (self.end_non_rigid_time - self.start_time)/60

            self.summary_df["mean_non_rigid_D"] = [mean_nr_d]*self.size
            self.summary_df["non_rigid_time_minutes"] = [non_rigid_min]*self.size

        return self.summary_df

    def register(self, brightfield_processing_cls=DEFAULT_BRIGHTFIELD_CLASS,
                 brightfield_processing_kwargs=DEFAULT_BRIGHTFIELD_PROCESSING_ARGS,
                 if_processing_cls=DEFAULT_FLOURESCENCE_CLASS,
                 if_processing_kwargs=DEFAULT_FLOURESCENCE_PROCESSING_ARGS,
                 reader_cls=None):

        """Register a collection of images

        This function will convert the slides to images, pre-process and normalize them, and
        then conduct rigid registration. Non-rigid registration will then be performed if the
        `non_rigid_registrar_cls` argument used to initialize the Valis object was not None.

        In addition to the objects returned, the desination directory (i.e. `dst_dir`)
        will contain thumbnails so that one can visualize the results: converted image
        thumbnails will be in "images/"; processed images in "processed/";
        rigidly aligned images in "rigid_registration/"; non-rigidly aligned images in "non_rigid_registration/";
        non-rigid deformation field images (i.e. warped grids colored by the direction and magntidue)
        of the deformation) will be in ""deformation_fields/". The size of these thumbnails
        is determined by the `thumbnail_size` argument used to initialze this object.

        One can get a sense of how well the registration worked by looking
        in the "overlaps/", which shows how the images overlap before
        registration, after rigid registration, and after non-rigid registration. Each image
        is created by coloring an inverted greyscale version of the processed images, and then
        blending those images.

        The "data/" directory will contain a pickled copy of this registrar, which can be
        later be opened (unpickled) and used to warp slides and/or point data.

        "data/" will also contain the `summary_df` saved as a csv file.


        Parameters
        ----------
        brightfield_processing_cls : preprocessing.ImageProcesser
            preprocessing.ImageProcesser used to pre-process brightfield images to make
            them look as similar as possible.

        brightfield_processing_kwargs : dict
            Dictionary of keyward arguments to be passed to `brightfield_processing_cls`

        if_processing_cls : preprocessing.ImageProcesser
            preprocessing.ImageProcesser used to pre-process immunofluorescent images
            to make them look as similar as possible.

        if_processing_kwargs : dict
            Dictionary of keyward arguments to be passed to `if_processing_cls`

        reader_cls : SlideReader, optional
            Uninstantiated SlideReader class that will convert
            the slide to an image, and also collect metadata. If None (the default),
            the appropriate SlideReader will be found by `slide_io.get_slide_reader`.
            This option is provided in case the slides cannot be opened by a current
            SlideReader class. In this case, the user should create a subclass of
            SlideReader. See slide_io.SlideReader for details.

        Returns
        -------
        rigid_registrar : SerialRigidRegistrar
            SerialRigidRegistrar object that performed the rigid registration.
            This object can be pickled if so desired

        non_rigid_registrar : SerialNonRigidRegistrar
            SerialNonRigidRegistrar object that performed serial
            non-rigid registration. This object can be pickled if so desired.

        summary_df : Dataframe
            `summary_df` contains various information about the registration.

            The "from" column is the name of the image, while the "to" column
            name of the image it was aligned to. "from" is analagous to "moving"
            or "current", while "to" is analgous to "fixed" or "previous".

            Columns begining with "original" refer to error measurements of the
            unregistered images. Those beginning with "rigid" or "non_rigid" refer
            to measurements related to rigid or non-rigid registration, respectively.

            Columns beginning with "mean" are averages of error measurements. In
            the case of errors based on feature distances (i.e. those ending in "D"),
            the mean is weighted by the number of feature matches between "from" and "to".

            Columns endining in "D" indicate the median distance between matched
            features in "from" and "to".

            Columns ending in "TRE" indicate the target registration error between
            "from" and "to".

            Columns ending in "mattesMI" contain measurements of the Mattes mutual
            information between "from" and "to".

            "processed_img_shape" indicates the shape (row, column) of the processed
            image actually used to conduct the registration

            "shape" is the shape of the slide at full resolution

            "aligned_shape" is the shape of the registered full resolution slide

            "physical_units" are the names of the pixels physcial unit, e.g. u'\u00B5m'

            "resolution" is the physical unit per pixel

            "name" is the name assigned to the Valis instance

            "rigid_time_minutes" is the total number of minutes it took
            to convert the images and then rigidly align them.

            "non_rigid_time_minutes" is the total number of minutes it took
            to convert the images, and then perform rigid -> non-rigid registration.

        """

        self.start_time = time()
        try:
            print("\n==== Converting images\n")
            self.convert_imgs(series=self.series, reader_cls=reader_cls)

            print("\n==== Processing images\n")
            self.brightfield_procsseing_fxn_str = brightfield_processing_cls.__name__
            self.if_processing_fxn_str = if_processing_cls.__name__
            self.process_imgs(brightfield_processing_cls, brightfield_processing_kwargs,
                              if_processing_cls, if_processing_kwargs)

            print("\n==== Rigid registraration\n")
            rigid_registrar = self.rigid_register()

            if rigid_registrar is False:
                return None, None, None

            if self.non_rigid_registrar_cls is not None:
                print("\n==== Non-rigid registraration\n")
                non_rigid_registrar = self.non_rigid_register(rigid_registrar,
                    brightfield_processing_cls=brightfield_processing_cls,
                    brightfield_processing_kwargs=brightfield_processing_kwargs,
                    if_processing_cls=if_processing_cls,
                    if_processing_kwargs=if_processing_kwargs)

            else:
                non_rigid_registrar = None

            print("\n==== Measuring error\n")
            aligned_slide_shape_rc = self.get_aligned_slide_shape(0)
            self.aligned_slide_shape_rc = aligned_slide_shape_rc
            for slide_obj in self.slide_dict.values():
                slide_obj.aligned_slide_shape_rc = aligned_slide_shape_rc

            error_df = self.measure_error()
            self.cleanup()

            pathlib.Path(self.data_dir).mkdir(exist_ok=True,  parents=True)
            f_out = os.path.join(self.data_dir, self.name + "_registrar.pickle")
            self.reg_f = f_out
            pickle.dump(self, open(f_out, 'wb'))

            data_f_out = os.path.join(self.data_dir, self.name + "_summary.csv")
            error_df.to_csv(data_f_out, index=False)
        except Exception as e:
            valtils.print_warning(e)
            print(traceback.format_exc())
            kill_jvm()
            return None, None, None


        return rigid_registrar, non_rigid_registrar, error_df

    def cleanup(self):
        """Remove objects that can't be pickled
        """
        self.rigid_reg_kwargs["feature_detector"] = None
        self.rigid_reg_kwargs["affine_optimizer"] = None
        self.non_rigid_registrar_cls = None
        self.rigid_registrar = None
        self.non_rigid_registrar = None

    def register_micro(self,  brightfield_processing_cls=DEFAULT_BRIGHTFIELD_CLASS,
                 brightfield_processing_kwargs=DEFAULT_BRIGHTFIELD_PROCESSING_ARGS,
                 if_processing_cls=DEFAULT_FLOURESCENCE_CLASS,
                 if_processing_kwargs=DEFAULT_FLOURESCENCE_PROCESSING_ARGS,
                 max_non_rigid_registartion_dim_px=DEFAULT_MAX_NON_RIGID_REG_SIZE,
                 non_rigid_registrar_cls=DEFAULT_NON_RIGID_CLASS,
                 non_rigid_reg_params=DEFAULT_NON_RIGID_KWARGS,
                 reference_img_f=None, align_to_reference=False, mask=None, tile_wh=DEFAULT_NR_TILE_WH):
        """Improve alingment of microfeatures by performing second non-rigid registration on larger images

        Caclculates additional non-rigid deformations using a larger image

        Parameters
        ----------
        brightfield_processing_cls : preprocessing.ImageProcesser
            preprocessing.ImageProcesser used to pre-process brightfield images to make
            them look as similar as possible.

        brightfield_processing_kwargs : dict
            Dictionary of keyward arguments to be passed to `brightfield_processing_cls`

        if_processing_cls : preprocessing.ImageProcesser
            preprocessing.ImageProcesser used to pre-process immunofluorescent images
            to make them look as similar as possible.

        if_processing_kwargs : dict
            Dictionary of keyward arguments to be passed to `if_processing_cls`

        max_non_rigid_registartion_dim_px : int, optional
             Maximum width or height of images used for non-rigid registration.
             If None, then the full sized image will be used. However, this
             may take quite some time to complete.

        reference_img_f : str, optional
            Filename of image that will be treated as the center of the stack.
            If None, the index of the middle image will be the reference, and
            images will be aligned towards it. If provided, images will be
            aligned to this reference.

        align_to_reference : bool, optional
            If `False`, images will be non-rigidly aligned serially towards the
            reference image. If `True`, images will be non-rigidly aligned
            directly to the reference image. If `reference_img_f` is None,
            then the reference image will be the one in the middle of the stack.

        non_rigid_registrar_cls : NonRigidRegistrar, optional
            Uninstantiated NonRigidRegistrar class that will be used to
            calculate the deformation fields between images. See
            the `non_rigid_registrars` module for a desciption of available
            methods. If a desired non-rigid registration method is not available,
            one can be implemented by subclassing.NonRigidRegistrar.

        non_rigid_reg_params: dictionary, optional
            Dictionary containing key, value pairs to be used to initialize
            `non_rigid_registrar_cls`.
            In the case where simple ITK is used by the, params should be
            a SimpleITK.ParameterMap. Note that numeric values nedd to be
            converted to strings. See the NonRigidRegistrar classes in
            `non_rigid_registrars` for the available non-rigid registration
            methods and arguments.

        """
        ref_slide = self.get_ref_slide()
        if mask is None:
            if ref_slide.non_rigid_reg_mask is not None:
                mask = ref_slide.non_rigid_reg_mask.copy()

        nr_reg_src, max_img_dim, non_rigid_reg_mask, full_out_shape_rc, mask_bbox_xywh = \
            self.prep_images_for_large_non_rigid_registration(max_img_dim=max_non_rigid_registartion_dim_px,
                                                                brightfield_processing_cls=brightfield_processing_cls,
                                                                brightfield_processing_kwargs=brightfield_processing_kwargs,
                                                                if_processing_cls=if_processing_cls,
                                                                if_processing_kwargs=if_processing_kwargs,
                                                                updating_non_rigid=True,
                                                                mask=mask)

        img0 = nr_reg_src[serial_non_rigid.IMG_LIST_KEY][0]
        img_specific_args = None
        write_dxdy = False

        self._non_rigid_bbox = mask_bbox_xywh
        self._full_displacement_shape_rc = full_out_shape_rc



        if isinstance(img0, pyvips.Image):

            # Have determined that these images will be too big
            msg = (f"Registration would more than {TILER_THRESH_GB} GB if all images opened in memory. "
                    f"Will use NonRigidTileRegistrar to register cooresponding tiles to reduce memory consumption, "
                    f"but this method is experimental")

            valtils.print_warning(msg)

            write_dxdy = True
            img_specific_args = {}
            for slide_obj in self.slide_dict.values():

                # Add registration parameters
                tiled_non_rigid_reg_params = {}
                tiled_non_rigid_reg_params[non_rigid_registrars.NR_CLS_KEY] = non_rigid_registrar_cls
                tiled_non_rigid_reg_params[non_rigid_registrars.NR_STATS_KEY] = self.target_processing_stats
                tiled_non_rigid_reg_params[non_rigid_registrars.NR_TILE_WH_KEY] = tile_wh

                if slide_obj.is_rgb:
                    processing_cls = brightfield_processing_cls
                    processing_args = brightfield_processing_kwargs
                else:
                    processing_cls = if_processing_cls
                    processing_args = if_processing_kwargs

                tiled_non_rigid_reg_params[non_rigid_registrars.NR_PROCESSING_CLASS_KEY] = processing_cls
                tiled_non_rigid_reg_params[non_rigid_registrars.NR_PROCESSING_KW_KEY] = processing_args

                img_specific_args[slide_obj.src_f] = tiled_non_rigid_reg_params

            non_rigid_registrar_cls = non_rigid_registrars.NonRigidTileRegistrar

        print("\n==== Performing microregistration\n")
        non_rigid_registrar = serial_non_rigid.register_images(src=nr_reg_src,
                                                               non_rigid_reg_class=non_rigid_registrar_cls,
                                                               non_rigid_reg_params=non_rigid_reg_params,
                                                               reference_img_f=reference_img_f,
                                                               mask=non_rigid_reg_mask,
                                                               align_to_reference=align_to_reference,
                                                               name=self.name,
                                                               img_params=img_specific_args
                                                               )

        pathlib.Path(self.micro_reg_dir).mkdir(exist_ok=True, parents=True)
        out_shape = full_out_shape_rc
        n_digits = len(str(self.size))
        micro_reg_imgs = [None] * self.size

        for slide_obj in self.slide_dict.values():

            nr_obj = non_rigid_registrar.non_rigid_obj_dict[slide_obj.name]
            is_array = False
            new_bk_dxdy = nr_obj.bk_dxdy
            new_fwd_dxdy = nr_obj.fwd_dxdy

            if np.any(non_rigid_registrar.shape != full_out_shape_rc):
                # Micro-registration perfomred on sub-region. Need to put in full image
                new_bk_dxdy = self.pad_displacement(new_bk_dxdy, full_out_shape_rc, mask_bbox_xywh)
                new_fwd_dxdy = self.pad_displacement(new_fwd_dxdy, full_out_shape_rc, mask_bbox_xywh)

            if not isinstance(slide_obj.bk_dxdy[0], pyvips.Image):
                current_bk_dxdy = warp_tools.numpy2vips(np.dstack(slide_obj.bk_dxdy)).cast("float")
                current_fwd_dxdy = warp_tools.numpy2vips(np.dstack(slide_obj.fwd_dxdy)).cast("float")
            else:
                current_bk_dxdy = slide_obj.bk_dxdy
                current_fwd_dxdy = slide_obj.fwd_dxdy

            slide_sxy = (np.array(out_shape)/np.array([current_bk_dxdy.height, current_bk_dxdy.width]))[::-1]
            if not np.all(slide_sxy == 1):
                scaled_bk_dx = float(slide_sxy[0])*current_bk_dxdy[0]
                scaled_bk_dy = float(slide_sxy[1])*current_bk_dxdy[1]
                current_bk_dxdy = scaled_bk_dx.bandjoin(scaled_bk_dy)
                current_bk_dxdy = warp_tools.resize_img(current_bk_dxdy, out_shape)

                scaled_fwd_dx = float(slide_sxy[0])*current_fwd_dxdy[0]
                scaled_fwd_dy = float(slide_sxy[1])*current_fwd_dxdy[1]
                current_fwd_dxdy = scaled_fwd_dx.bandjoin(scaled_fwd_dy)
                current_fwd_dxdy = warp_tools.resize_img(current_fwd_dxdy, out_shape)

            updated_bk_dxdy = current_bk_dxdy + new_bk_dxdy
            updated_fwd_dxdy = current_fwd_dxdy + new_fwd_dxdy

            if is_array:
                updated_bk_dxdy = warp_tools.vips2numpy(updated_bk_dxdy)
                updated_fwd_dxdy = warp_tools.vips2numpy(updated_fwd_dxdy)

            if not write_dxdy:
                slide_obj.bk_dxdy = np.array([updated_bk_dxdy[..., 0], updated_bk_dxdy[..., 1]])
                slide_obj.fwd_dxdy = np.array([updated_fwd_dxdy[..., 0], updated_fwd_dxdy[..., 1]])
            else:
                pathlib.Path(self.displacements_dir).mkdir(exist_ok=True, parents=True)
                slide_obj.stored_dxdy = True

                bk_dxdy_f, fwd_dxdy_f = slide_obj.get_displacement_f()
                slide_obj._bk_dxdy_f = bk_dxdy_f
                slide_obj._fwd_dxdy_f = fwd_dxdy_f

                # Save space by only writing the necessary areas. Most displacements may be 0
                cropped_bk_dxdy = updated_bk_dxdy.extract_area(*mask_bbox_xywh)
                cropped_fwd_dxdy = updated_fwd_dxdy.extract_area(*mask_bbox_xywh)

                cropped_bk_dxdy.cast("float").tiffsave(slide_obj._bk_dxdy_f, compression="lzw", lossless=True, tile=True, bigtiff=True)
                cropped_fwd_dxdy.cast("float").tiffsave(slide_obj._fwd_dxdy_f, compression="lzw", lossless=True, tile=True, bigtiff=True)

            if not slide_obj.is_rgb:
                img_to_warp = slide_obj.processed_img
            else:
                img_to_warp = slide_obj.image

            micro_reg_img = slide_obj.warp_img(img_to_warp, non_rigid=True, crop=self.crop)


            img_save_id = str.zfill(str(slide_obj.stack_idx), n_digits)
            micro_fout = os.path.join(self.micro_reg_dir, f"{img_save_id}_{slide_obj.name}.png")
            micro_thumb = self.create_thumbnail(micro_reg_img)
            warp_tools.save_img(micro_fout, micro_thumb)

            processed_micro_reg_img = slide_obj.warp_img(slide_obj.processed_img)
            micro_reg_imgs[slide_obj.stack_idx] = processed_micro_reg_img

        pickle.dump(self, open(self.reg_f, 'wb'))

        micro_overlap = self.draw_overlap_img(micro_reg_imgs)
        self.micro_reg_overlap_img = micro_overlap
        overlap_img_fout = os.path.join(self.overlap_dir, self.name + "_micro_reg.png")
        warp_tools.save_img(overlap_img_fout, micro_overlap, thumbnail_size=self.thumbnail_size)

        print("\n==== Measuring error\n")
        error_df = self.measure_error()
        data_f_out = os.path.join(self.data_dir, self.name + "_summary.csv")
        error_df.to_csv(data_f_out, index=False)

        return non_rigid_registrar, error_df



    def get_aligned_slide_shape(self, level):
        """Get size of aligned images

        Parameters
        ----------
        level : int, float
            If `level` is an integer, then it is assumed that `level` is referring to
            the pyramid level that will be warped.

            If `level` is a float, it is assumed `level` is how much to rescale the
            registered image's size.

        """

        ref_slide = self.get_ref_slide()

        if np.issubdtype(type(level), np.integer):
            n_levels = len(ref_slide.slide_dimensions_wh)
            if level >= n_levels:
                msg = (f"requested to scale transformation for pyramid level {level}, ",
                    f"but the image only has {n_levels} (starting from 0). ",
                    f"Will use level {level-1}, which is the smallest level")
                valtils.print_warning(msg)
                level = level - 1

            slide_shape_rc = ref_slide.slide_dimensions_wh[level][::-1]
            s_rc = (slide_shape_rc/np.array(ref_slide.processed_img_shape_rc))
        else:
            s_rc = level

        aligned_out_shape_rc = np.ceil(np.array(ref_slide.reg_img_shape_rc)*s_rc).astype(int)

        return aligned_out_shape_rc

    def get_slide(self, src_f):
        """Get Slide

        Get the Slide associated with `src_f`.
        Slide store registration parameters and other metadata about
        the slide associated with `src_f`. Slide can also:

        * Convert the slide to a numpy array (Slide.slide2image)
        * Convert the slide to a pyvips.Image (Slide.slide2vips)
        * Warp the slide (Slide.warp_slide)
        * Save the warped slide as an ome.tiff (Slide.warp_and_save_slide)
        * Warp an image of the slide (Slide.warp_img)
        * Warp points (Slide.warp_xy)
        * Warp points in one slide to their position in another unwarped slide (Slide.warp_xy_from_to)
        * Access slide ome-xml (Slide.original_xml)

        See Slide for more details.

        Parameters
        ----------
        src_f : str
            Path to the slide

        Returns
        -------
        slide_obj : Slide
            Slide associated with src_f

        """

        slide_name = valtils.get_name(src_f)
        slide_obj =  self.slide_dict[slide_name]

        return slide_obj

    @valtils.deprecated_args(perceputally_uniform_channel_colors="colormap")
    def warp_and_save_slides(self, dst_dir, level = 0, non_rigid=True,
                             crop=True,
                             colormap=None,
                             interp_method="bicubic",
                             tile_wh=None, compression="lzw"):

        f"""Warp and save all slides

        Each slide will be saved as an ome.tiff. The extension of each file will
        be changed to ome.tiff if it is not already.

        Parameters
        ----------
        dst_dir : str
            Path to were the warped slides will be saved.

        level : int, optional
            Pyramid level to be warped. Default is 0, which means the highest
            resolution image will be warped and saved.

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied. Default is True

        crop: bool, str
            How to crop the registered images. If `True`, then the same crop used
            when initializing the `Valis` object will be used. If `False`, the
            image will not be cropped. If "overlap", the warped slide will be
            cropped to include only areas where all images overlapped.
            "reference" crops to the area that overlaps with the reference image,
            defined by `reference_img_f` when initialzing the `Valis object`.

        colormap : list
            List of RGB colors (0-255) to use for channel colors

        interp_method : str
            Interpolation method used when warping slide. Default is "bicubic"

        tile_wh : int, optional
            Tile width and height used to save image

        compression : str, optional
            Compression method used to save ome.tiff . Default is lzw, but can also
            be jpeg or jp2k. See pyips for more details.

        """
        pathlib.Path(dst_dir).mkdir(exist_ok=True, parents=True)

        for slide_obj in tqdm.tqdm(self.slide_dict.values()):

            # if reference image, then skip and copy ref to folder instead?
            if(self.reference_img_f == slide_obj.src_f):
                print("copying reference...")
                shutil.copy2(self.reference_img_f, dst_dir)
                continue

            slide_cmap = None
            if colormap is not None:
                chnl_names = slide_obj.reader.metadata.channel_names
                if chnl_names is not None:
                    if len(colormap) >= len(chnl_names):
                        slide_cmap = {chnl_names[i]:tuple(colormap[i]) for i in range(len(chnl_names))}

                    else:
                        msg = f'{slide_obj.name} has {len(chnl_names)} but colormap only has {len(colormap)} colors'
                        valtils.print_warning(msg)

            dst_f = os.path.join(dst_dir, slide_obj.name + ".ome.tiff")
            slide_obj.warp_and_save_slide(dst_f=dst_f, level = level,
                                          non_rigid=non_rigid,
                                          crop=crop,
                                          interp_method=interp_method,
                                          colormap=slide_cmap,
                                          tile_wh=tile_wh, compression=compression)

    @valtils.deprecated_args(perceputally_uniform_channel_colors="colormap")
    def warp_and_merge_slides(self, dst_f=None, level=0, non_rigid=True,
                              crop=True, channel_name_dict=None,
                              src_f_list=None, colormap=None,
                              drop_duplicates=True, tile_wh=None,
                              interp_method="bicubic", compression="lzw"):

        """Warp and merge registered slides

        Parameters
        ----------
        dst_f : str, optional
            Path to were the warped slide will be saved. If None, then the slides will be merged
            but not saved.

        level : int, optional
            Pyramid level to be warped. Default is 0, which means the highest
            resolution image will be warped and saved.

        non_rigid : bool, optional
            Whether or not to conduct non-rigid warping. If False,
            then only a rigid transformation will be applied. Default is True

        crop: bool, str
            How to crop the registered images. If `True`, then the same crop used
            when initializing the `Valis` object will be used. If `False`, the
            image will not be cropped. If "overlap", the warped slide will be
            cropped to include only areas where all images overlapped.
            "reference" crops to the area that overlaps with the reference image,
            defined by `reference_img_f` when initialzing the `Valis object`.

        channel_name_dict : dict of lists, optional.
            key =  slide file name, value = list of channel names for that slide. If None,
            the the channel names found in each slide will be used.

        src_f_list : list of str, optionaal
            List of paths to slide to be warped. If None (the default), Valis.original_img_list
            will be used. Otherwise, the paths to which `src_f_list` points to should
            be an alternative copy of the slides, such as ones that have undergone
            processing (e.g. stain segmentation), had a mask applied, etc...

        colormap : list
            List of RGB colors (0-255) to use for channel colors

        drop_duplicates : bool, optional
            Whether or not to drop duplicate channels that might be found in multiple slides.
            For example, if DAPI is in multiple slides, then the only the DAPI channel in the
            first slide will be kept.

        tile_wh : int, optional
            Tile width and height used to save image

        interp_method : str
            Interpolation method used when warping slide. Default is "bicubic"

        compression : str
            Compression method used to save ome.tiff . Default is lzw, but can also
            be jpeg or jp2k. See pyips for more details.

        Returns
        -------
        merged_slide : pyvips.Image
            Image with all channels merged. If `drop_duplicates` is True, then this
            will only contain unique channels.

        all_channel_names : list of str
            Name of each channel in the image

        ome_xml : str
            OME-XML string containing the slide's metadata

        """

        if channel_name_dict is not None:
            channel_name_dict_by_name = {valtils.get_name(k):channel_name_dict[k] for k in channel_name_dict}

        if src_f_list is None:
            src_f_list = self.original_img_list

        all_channel_names = []
        merged_slide = None

        for f in src_f_list:
            slide_name = valtils.get_name(os.path.split(f)[1])
            slide_obj = self.slide_dict[slide_name]

            warped_slide = slide_obj.warp_slide(level, non_rigid=non_rigid,
                                                crop=crop,
                                                interp_method=interp_method)

            keep_idx = list(range(warped_slide.bands))
            if channel_name_dict is not None:
                slide_channel_names = channel_name_dict_by_name[slide_obj.name]

                if drop_duplicates:
                    keep_idx = [idx for idx  in range(len(slide_channel_names)) if
                                slide_channel_names[idx] not in all_channel_names]

            else:
                slide_channel_names = slide_obj.reader.metadata.channel_names
                slide_channel_names = [c + " (" + slide_name + ")" for c in  slide_channel_names]

            if drop_duplicates and warped_slide.bands != len(keep_idx):
                keep_channels = [warped_slide[c] for c in keep_idx]
                slide_channel_names = [slide_channel_names[idx] for idx in keep_idx]
                if len(keep_channels) == 1:
                    warped_slide = keep_channels[0]
                else:
                    warped_slide = keep_channels[0].bandjoin(keep_channels[1:])
            print(f"merging {', '.join(slide_channel_names)}")

            if merged_slide is None:
                merged_slide = warped_slide
            else:
                merged_slide = merged_slide.bandjoin(warped_slide)

            all_channel_names.extend(slide_channel_names)


        if colormap is not None:
            if len(colormap) >= len(all_channel_names):
                cmap_dict = {all_channel_names[i]:tuple(colormap[i]) for i in range(len(all_channel_names))}

            else:
                msg = f'Merged image has {len(all_channel_names)} but colormap only has {len(colormap)} colors'
                valtils.print_warning(msg)

        else:
            cmap_dict = None

        px_phys_size = slide_obj.reader.scale_physical_size(level)
        bf_dtype = slide_io.vips2bf_dtype(merged_slide.format)
        out_xyczt = slide_io.get_shape_xyzct((merged_slide.width, merged_slide.height), merged_slide.bands)

        ome_xml_obj = slide_io.create_ome_xml(out_xyczt, bf_dtype, is_rgb=False,
                                              pixel_physical_size_xyu=px_phys_size,
                                              channel_names=all_channel_names,
                                              colormap=cmap_dict)
        ome_xml = ome_xml_obj.to_xml()

        if dst_f is not None:
            dst_dir = os.path.split(dst_f)[0]
            pathlib.Path(dst_dir).mkdir(exist_ok=True, parents=True)
            if tile_wh is None:
                tile_wh = slide_obj.reader.metadata.optimal_tile_wh
                if level != 0:
                    down_sampling = np.mean(slide_obj.slide_dimensions_wh[level]/slide_obj.slide_dimensions_wh[0])
                    tile_wh = int(np.round(tile_wh*down_sampling))
                    tile_wh = tile_wh - (tile_wh % 16)  # Tile shape must be multiple of 16
                    if tile_wh < 16:
                        tile_wh = 16
                    if np.any(np.array(out_xyczt[0:2]) < tile_wh):
                        tile_wh = min(out_xyczt[0:2])

            slide_io.save_ome_tiff(merged_slide, dst_f=dst_f,
                                   ome_xml=ome_xml,tile_wh=tile_wh,
                                   compression=compression)

        return merged_slide, all_channel_names, ome_xml

