import os
import shutil
import re

folder_dir = r"G:\My Drive\Yale-QIF-HER2\WTSVal_RCyte\sorted_HS-HER2_WTSVal"
folders = [
	'S20_25784_HEnIF',
	'S18_28210_HEnIF',
	'S20_27517_HEnIF',
	'S20_26248_01-02_HEnIF',
	'S20_27495_01-02_HEnIF',
	'S20_03309_HEnIF',
	'S20_25680_HEnIF',
	'S20_25677_HEnIF',
	'S18_21925_HEnIF',
	'S18_25229_HEnIF',
	'S18_31022_01-02_HEnIF',
	'S18_31022_01-01_HEnIF',
	'S20_26248_HEnIF',
	'S20_26216_HEnIF',
	'S18_13390_HEnIF',
	'S20_27495_HEnIF',
	'S20_26834_HEnIF',
	'S18_22785_HEnIF',
	'S18_27040_HEnIF',
	'S20_25771_HEnIF',
	'S20_25420_HEnIF',
	'S18_26442_HEnIF',
	'S20_07650_HEnIF',
	'S18_21762_01-02_HEnIF',
	'S20_26650_HEnIF',
	'S18_21762_01-01_HEnIF'
]

for f in folders:
	# get the contents and move it
	for i in os.listdir(os.path.join(folder_dir, f)):
		if os.path.isdir(os.path.join(folder_dir, f, i)):
			continue
		print("moving {}/{}".format(f, i))
		shutil.move(os.path.join(folder_dir, f, i),
		            os.path.join(folder_dir, i))