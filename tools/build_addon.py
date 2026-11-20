"""Build the installable add-on zip: dist/phantom_dust_stage-<version>.zip

  python tools/build_addon.py

Install in Blender: Edit > Preferences > Get Extensions > (menu) Install from Disk.
The zip holds the add-on folder's files at its root (pdstage/ is inside it).
"""
import os, re, sys, zipfile

root = os.path.abspath(os.path.join(os.path.dirname(os.path.abspath(__file__)), '..'))
addon = os.path.join(root, 'addon', 'phantom_dust_stage')
manifest = open(os.path.join(addon, 'blender_manifest.toml')).read()
version = re.search(r'^version\s*=\s*"([^"]+)"', manifest, re.M).group(1)
os.makedirs(os.path.join(root, 'dist'), exist_ok=True)
out = os.path.join(root, 'dist', 'phantom_dust_stage-%s.zip' % version)


def add_tree(z, src, prefix):
    for d, dirs, files in os.walk(src):
        dirs[:] = [x for x in dirs if x != '__pycache__']
        for f in files:
            if f.endswith('.pyc'):
                continue
            p = os.path.join(d, f)
            z.write(p, os.path.join(prefix, os.path.relpath(p, src)).replace('\\', '/'))


with zipfile.ZipFile(out, 'w', zipfile.ZIP_DEFLATED) as z:
    add_tree(z, addon, '')
print('wrote', out)
for n in zipfile.ZipFile(out).namelist():
    print('  ', n)
