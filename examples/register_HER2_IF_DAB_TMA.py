import time
import os
from valis import registration
import _pickle as cPickle
import geojson
import numpy as np
# import shapely
# from valis.slide_io import VipsSlideReader, BioFormatsSlideReader
# import matplotlib
# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt


comb_folders =[
    "HER2DAB_alignment"
]
main_dir = "/home/cjr66/scratch60/"

DEFAULT_FLOURESCENCE_PROCESSING_ARGS = {"channel": "DAPI", "adaptive_eq": True}
# DEFAULT_BRIGHTFIELD_PROCESSING_ARGS = {'c': preprocessing.DEFAULT_COLOR_STD_C, "h": 0}

print(comb_folders)
for cf in comb_folders:
    print("working on {}".format(cf))
    slide_src_dir = os.path.join(main_dir, cf)
    results_dst_dir = os.path.join(main_dir, "expected_results/registration")
    # H&E as reference image
    ref_f = [f for f in os.listdir(os.path.join(main_dir, cf)) if f.endswith(".ome.tiff")][0]
    target_fs = [f for f in os.listdir(os.path.join(main_dir, cf)) if not f.endswith(".ome.tiff")]
    print(ref_f)
    print(target_fs)
    try:
        print("trying to load registrar data from saved pickle file...")
        with open(os.path.join(results_dst_dir, cf, "data", "{}_registrar.pickle".format(cf)), 'rb') as regfile:
            registrar = cPickle.load(regfile)
            print("loading from pickle...")
    except Exception as e:
        # print(e)
        # continue
        # Create a Valis object and use it to register the slides in slide_src_dir
        start = time.time()
        registrar = registration.Valis(slide_src_dir, results_dst_dir,
                                     reference_img_f=ref_f, align_to_reference=True,
                                     # max_image_dim_px=800,
                                     # max_processed_image_dim_px=800,
                                     # max_non_rigid_registartion_dim_px=800
                                     )

        # reader_cls = VipsSlideReader
        rigid_registrar, non_rigid_registrar, error_df = registrar.register(if_processing_kwargs=DEFAULT_FLOURESCENCE_PROCESSING_ARGS)
        stop = time.time()
        elapsed = stop - start
        print(f"regisration time is {elapsed/60} minutes")
    # Check results in registered_slide_dst_dir. If they look good, warp the annotation points using reference and target images
    # warp points from reference to target image inside a QuPath geojson
    #Valis only warps ndarray points...
    # So you have to 1) subdivide all the polygons or multipolygons inside the geojson,
    # 2) warp,
    # 3) then reconstruct the geojson with the warped points
    # Read in your annotations here and name as annotation_pt_xy.
    # Be sure they are in pixel units, not physical units. See below on how convert them to pixel units if the annotations are in physical units
    # ref_f is the name of the slide the annotations came from
    # target_img_f  is the name of the slide you want to transfer the annotations to
    geojson_folder = "/home/cjr66/scratch60/expected_results/geojson"
    for target_img_f in target_fs:
      print("working on {}".format(target_img_f))
      if target_img_f != "HER2DAB_263-6-58_1_250.svs":
        continue
    # with open(os.path.join(geojson_folder, "263_3_60_29D8HER2_simple.geojson")) as f:
    # Is there a better way to copy feature collection instead of as reference and reloading?
      with open(os.path.join(geojson_folder, "263_3_60_29D8HER2@20230118_214056_129289_jp2k_Hflip.geojson")) as f:
          ref_geojson = geojson.load(f)
      # Copy generates a dict object instead of feature colelction.... copy as ref for now....
      warped_geojson = ref_geojson
      total_feat = len(ref_geojson['features'])
      annotation_source_slide = registrar.get_slide(ref_f)
      target_slide = registrar.get_slide(target_img_f)
      for i,feat in enumerate(ref_geojson['features']):
          print("registering {}/{} features".format(i+1, total_feat))
          if feat['geometry']['type'] == 'MultiPolygon':
              for j,multipoly in enumerate(feat['geometry']['coordinates']):
                  for k,polypoints in enumerate(multipoly):
                      polypoints = np.array(polypoints)
                      annotations_on_target_slide_xy = annotation_source_slide.warp_xy_from_to(polypoints, target_slide, non_rigid=True)
                      warped_geojson['features'][i]['geometry']['coordinates'][j][k] = annotations_on_target_slide_xy.tolist()
          else:
              for k, polypoints in enumerate(feat['geometry']['coordinates']):
                  polypoints = np.array(polypoints)
                  annotations_on_target_slide_xy = annotation_source_slide.warp_xy_from_to(polypoints, target_slide, non_rigid=True)
                  warped_geojson['features'][i]['geometry']['coordinates'][k] = annotations_on_target_slide_xy.tolist()

      print("{}: writing warped geojson file".format(target_img_f))
      with open(os.path.join(geojson_folder, "{}.geojson".format(os.path.splitext(target_img_f)[0])), "w") as geo_file:
          geo_file.write(geojson.dumps(warped_geojson, indent=4))

# Shutdown the JVM
registration.kill_jvm()