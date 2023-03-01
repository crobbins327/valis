import os
import shutil
import re

folder_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-17-22/rigid_registered_slides"
folders = os.listdir(folder_dir)

for f in folders:
	# get the contents and move it
	for i in os.listdir(os.path.join(folder_dir, f)):
		if os.path.isdir(os.path.join(folder_dir, f, i)):
			continue
		print("moving {}/{}".format(f, i))
		shutil.move(os.path.join(folder_dir, f, i),
		            os.path.join(folder_dir, i))

import os
import re
def replaceUnderscores(strInput, slice = [0, -1]):
	subStr = strInput[slice[0]:slice[1]]
	# Check if subString has underscores to replace
	if(re.search("_", subStr)):
		repStr = subStr.replace("_", "-")
		newStr = strInput[:slice[0]] + repStr + strInput[slice[1]:]
		return newStr, True
	else:
		return strInput, False
folder_dir = r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/rigid_registered_slides"
files = os.listdir(folder_dir)
for f in files:
	if os.path.isdir(os.path.join(folder_dir, f)):
		continue
	newName, replaceBool = replaceUnderscores(f, slice=[0, 11])
	if(replaceBool):
		print("remaming {} to {}".format(f, newName))
		os.rename(os.path.join(folder_dir, f), os.path.join(folder_dir, newName))

