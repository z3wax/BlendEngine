#!/usr/bin/env python3
"""Use the audited native IPA packager with the Z3WAX project layout."""
import pathlib, sys, shutil
ROOT=pathlib.Path(__file__).resolve().parents[2]
sys.path.insert(0,str(ROOT/'tools/ios'))
import build_ios as native
from project import ios_preset

def prepare(source,destination,*,bundle_id,version,build):
 source=pathlib.Path(source).resolve();destination=pathlib.Path(destination).resolve()
 if source==destination or source in destination.parents:raise ValueError('Output must be outside source')
 for name in ['project.godot','main.tscn','main.gd','assets/character.glb','assets/outpost.glb']:
  if not (source/name).is_file():raise ValueError('Missing '+name)
 shutil.copytree(source,destination,ignore=shutil.ignore_patterns('.godot','build','*.import','*.blend'))
 (destination/'export_presets.cfg').write_text(ios_preset(bundle_id,version,build).replace('assets/*.json,','assets/Textures/*.png,').replace('tests/*,',''))
 return destination
native.prepare_project=prepare
if __name__=='__main__':native.main()
