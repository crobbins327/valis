import time
import os
from valis import registration
# import _pickle as cPickle
# from valis.slide_io import VipsSlideReader, BioFormatsSlideReader
# import matplotlib
# matplotlib.use('TkAgg')
import matplotlib.pyplot as plt

# slide_src_dir = "/content/drive/MyDrive/Yale-QIF-HER2/H&E/extra/S18_21762-IHC0"
# results_dst_dir = "/content/drive/MyDrive/Yale-QIF-HER2/H&E/expected_results/registration"
missing = [
    # "S18_27040_HEnIF", no HE
    # "S20_25784_HEnIF", needs to be trimmed
    ]

serial_folders = [
    # 'S18_26442_HEnIF',
    # 'S18_13390_HEnIF',
    # 'S18_31022_01-02_HEnIF',
    # 'S18_21762_01-01_HEnIF',
    # 'S18_31022_01-01_HEnIF',
    'S18_25229_HEnIF',
    'S18_22785_HEnIF',
    'S18_21762_01-02_HEnIF',
    'S18_21925_HEnIF',
    'S18_28210_HEnIF',
    # 'S18_27040_HEnIF',
    # 'S20_25680_HEnIF',
    # 'S20_25677_HEnIF',
    # 'S20_25771_HEnIF',
    # 'S20_07650_HEnIF',
    # 'S20_27495_HEnIF',
    # 'S20_26216_HEnIF',
    # 'S20_26834_HEnIF',
    # 'S20_26650_HEnIF',
    # 'S20_03309_HEnIF',
    # 'S20_27517_HEnIF',
    # 'S20_26248_01-02_HEnIF',
    # 'S20_25420_HEnIF',
    # 'S20_26248_HEnIF',
    # 'S20_25784_HEnIF',
    # 'S20_27495_01-02_HEnIF',
                  ]
main_dir = "/home/cjr66/scratch60/HS-HER2/5ms_HS-HER2_WTSVal"
os.listdir(main_dir)

DEFAULT_FLOURESCENCE_PROCESSING_ARGS = {"channel": "DAPI", "adaptive_eq": True}
# DEFAULT_BRIGHTFIELD_PROCESSING_ARGS = {'c': preprocessing.DEFAULT_COLOR_STD_C, "h": 0}

for cf in serial_folders:
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
                                 max_image_dim_px=1500,
                                 max_processed_image_dim_px=1500,
                                 max_non_rigid_registartion_dim_px=1500
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
  registrar.warp_and_save_slides(registered_slide_dst_dir, non_rigid = True, perceputally_uniform_channel_colors=True, compression='jp2k')
  stop = time.time()
  elapsed = stop - start
  print(f"saving {registrar.size} slides took {elapsed/60} minutes")



# Shutdown the JVM
registration.kill_jvm()