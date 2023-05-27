import os
import pandas as pd
import re

folder_dirs = [
    "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/9-30-22/combined",
    "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-05-22/combined",
	"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-13-22/combined",
    "/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/10-17-22/combined",
]
map = dict()
for folder_dir in folder_dirs:
    folders = os.listdir(folder_dir)
    for f in folders:
        if re.match(r"^expected_results|^515", f):
            continue
        # get the contents and move it
        ome_file = [i for i in os.listdir(os.path.join(folder_dir, f)) if i.endswith("ome.tiff")][0]
        ref_file = [j for j in os.listdir(os.path.join(folder_dir, f)) if j.endswith(".svs")][0]
        map[ref_file] = ome_file

map_df = pd.DataFrame.from_dict(map, orient="index")
map_df = map_df.reset_index()
map_df.columns = ["HE_img", "IF_img"]
map_df.to_csv(r"/home/cjr66/scratch60/HS-HER2/HS-HER2 Prospective/[Aug-Oct]HS-HER2_HE_IF_image-map.csv", index=False)