import time
import os
from valis import registration
# import _pickle as cPickle
# from valis.slide_io import VipsSlideReader, BioFormatsSlideReader
# import matplotlib
# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt

# 09-30-22
missing = [
# 'S22_20914_HEnIF',
# 'OS22_09541_HEnIF',
# 'OS22_09539_HEnIF',
# 'S22_20817_HEnIF',
]
# comb_folders =[
#     'S22-23380_HEnIF',
#     'S22_19911_HEnIF',
#     'S22-21890_HEnIF',
#     'S22_21237_HEnIF',
#     'S22-23643_HEnIF',
#     'S22_20113_HEnIF',
#     'S22_20903_HEnIF',
#     'S22-22534_HEnIF',
#     'S22_21024_HEnIF',
#     'S22-21383_HEnIF',
    # 'S22_19983_HEnIF',
    # 'OS22-10536_HEnIF',
    # 'S22_20518_HEnIF',
    # 'OS22-10651_HEnIF',
    # 'S22-21560_HEnIF',
    # 'S22_21304_HEnIF',
    # 'S22_19910_HEnIF',
    # 'S22_19892_HEnIF',
    # 'S22_20550_HEnIF',
    # 'S22_21224_HEnIF',
    # 'S22_20246_HEnIF',
    # 'S22-22036_HEnIF',
    # 'S22-21770_HEnIF',
    # 'S22-23689_HEnIF',
    # 'S22_20697_HEnIF',
    # 'S22_19912_HEnIF',
    # 'S22-21803_HEnIF',
    # 'S22-21888_HEnIF',
    # 'S22_20815_HEnIF',
    # 'S22-23119_HEnIF',
    # 'OS22_09371_HEnIF',
    # 'S22-22206_HEnIF',
    # 'S22_09773_HEnIF',
    # 'S22-22413_HEnIF',
    # 'S22_20904_HEnIF',
    # 'S22_20908_HEnIF',
    # 'S22_20626_HEnIF',
    # 'S22-21678_HEnIF',
    # 'OS22_09780_HEnIF',
    # 'S22_20613_HEnIF',
    # 'S22-22201_HEnIF',
    # 'S22-22978_HEnIF',
    # 'S22_20288_HEnIF'
# ]
# main_dir = "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/combined"
# os.listdir(main_dir)

# 10-05-22
# missing = [
    # 'S22-23117-12_HEnIF',
    # 'S22-23088-02-01-10_HEnIF',
    # 'S22-23088-01-01-10_HEnIF',
    # 'S22-22955-10_HEnIF'
    # 'S22-22827-13_HEnIF',
    # ]
comb_folders = [
    # 'S22-249341-12_HEnIF',
    'S22-24508-12_HEnIF',
    'S22-24124-12_HEnIF',
    'S22-24779-13_HEnIF',
    'S22-24658-12_HEnIF',
    'OS22-11142-12_HEnIF',
    'S22-24971-12_HEnIF',
    'S22-24970-12_HEnIF',
    'S22-22600-11_HEnIF',
    'S22-24622-12_HEnIF',
    'S22-24099-13_HEnIF',
    'S22-24904-13_HEnIF',
]
main_dir = "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-05-22/combined"
# os.listdir(main_dir)

DEFAULT_FLOURESCENCE_PROCESSING_ARGS = {"channel": "DAPI", "adaptive_eq": True}
# DEFAULT_BRIGHTFIELD_PROCESSING_ARGS = {'c': preprocessing.DEFAULT_COLOR_STD_C, "h": 0}

print(comb_folders)
for cf in comb_folders:
  print("working on {}".format(cf))
  slide_src_dir = os.path.join(main_dir, cf)
  results_dst_dir = os.path.join(main_dir, "expected_results/registration")
  # H&E as reference image
  ref_f = [f for f in os.listdir(os.path.join(main_dir, cf)) if f.endswith(".svs")][0]
  print(ref_f)
  # try:
  #   print("trying to load registrar data from saved pickle file...")
  #   with open(os.path.join(results_dst_dir, cf, "data", "{}_registrar.pickle".format(cf)), 'rb') as regfile:
  #     registrar = cPickle.load(regfile)
  #   print("loading from pickle...")
  # except:
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

  # Check results in registered_slide_dst_dir. If they look good, export the registered slides
  registered_slide_dst_dir = os.path.join(main_dir, "expected_results/nonrigid_registered_slides", registrar.name)
  # registered_slide_dst_dir = os.path.join(main_dir, "expected_results/rigid_registered_slides", registrar.name)
  start = time.time()
  registrar.warp_and_save_slides(registered_slide_dst_dir, non_rigid = True, perceputally_uniform_channel_colors=False, compression='jp2k')
  stop = time.time()
  elapsed = stop - start
  print(f"saving {registrar.size} slides took {elapsed/60} minutes")



# Shutdown the JVM
registration.kill_jvm()