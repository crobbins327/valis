import time
import os
from valis import registration
import _pickle as cPickle
from valis.slide_io import VipsSlideReader, BioFormatsSlideReader
import matplotlib
matplotlib.use('TkAgg')
import matplotlib.pyplot as plt


# slide_src_dir = "/content/drive/MyDrive/Yale-QIF-HER2/H&E/extra/S18_21762-IHC0"
# results_dst_dir = "/content/drive/MyDrive/Yale-QIF-HER2/H&E/expected_results/registration"

serial_folders = [
                  'S20_27517_HEnIF',
                  ]
main_dir = r"G:\My Drive\Yale-QIF-HER2\WTSVal_RCyte\5ms_HS-HER2_WTSVal"
DEFAULT_FLOURESCENCE_PROCESSING_ARGS = {"channel": "DAPI", "adaptive_eq": True}
# DEFAULT_BRIGHTFIELD_PROCESSING_ARGS = {'c': preprocessing.DEFAULT_COLOR_STD_C, "h": 0}

for cf in serial_folders:
  print("working on {}".format(cf))
  slide_src_dir = os.path.join(main_dir, cf)
  results_dst_dir = os.path.join(main_dir, "expected_results/registration")


  # try:
  #   print("trying to load registrar data from saved pickle file...")
  #   with open(os.path.join(results_dst_dir, cf, "data", "{}_registrar.pickle".format(cf)), 'rb') as regfile:
  #     registrar = cPickle.load(regfile)
  #   print("loading from pickle...")
  # except:
  # Create a Valis object and use it to register the slides in slide_src_dir
  start = time.time()
  registrar = registration.Valis(slide_src_dir, results_dst_dir,
                                 reference_img_f="S20_27517_1_1-2_2.svs", align_to_reference=True,
                                 max_image_dim_px=10000,
                                 max_processed_image_dim_px=10000,
                                 max_non_rigid_registartion_dim_px=10000
                                 )
  # reader_cls = VipsSlideReader
  rigid_registrar, non_rigid_registrar, error_df = registrar.register(if_processing_kwargs=DEFAULT_FLOURESCENCE_PROCESSING_ARGS)
  stop = time.time()
  elapsed = stop - start
  print(f"regisration time is {elapsed/60} minutes")

  # Check results in registered_slide_dst_dir. If they look good, export the registered slides
  # registered_slide_dst_dir = os.path.join(main_dir, "expected_results/nonrigid_registered_slides", registrar.name)
  registered_slide_dst_dir = os.path.join(main_dir, "expected_results/rigid_registered_slides", registrar.name)
  start = time.time()
  registrar.warp_and_save_slides(registered_slide_dst_dir, non_rigid = False, perceputally_uniform_channel_colors=True, compression='jp2k')
  stop = time.time()
  elapsed = stop - start
  print(f"saving {registrar.size} slides took {elapsed/60} minutes")



# Shutdown the JVM
registration.kill_jvm()