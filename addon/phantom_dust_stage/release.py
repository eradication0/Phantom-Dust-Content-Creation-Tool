"""Release: package the map as a mod release .zip (the community's map mod format, as Phantom Dust: Rebirth reads
it) and optionally publish it as a GitHub release.

The zip holds, at its root:
    mod-info.ini     id, author, name, ver, desc, category, preview (the fields below)
    preview.png      256 x 112, shown in the game's map picker and Mods list
    <File>.alr       the map's model file   } exported from this scene, as Export does
    <File>.dat       the map's stage file   }
and is named <Name>.<ver>.zip. Rebirth's mod catalog takes a mod's newest GitHub release and its first .zip (GitHub
works out the sha256 the games check), so publishing a new release is all an update needs.

Publishing uses a GitHub token from the add-on preferences (or the GH_TOKEN / GITHUB_TOKEN environment variable):
a fine-grained token with "Contents: read and write" on the mod's repository. The release tag is the version.
"""
import json
import os
import shutil
import tempfile
import urllib.error
import urllib.request
import uuid
import zipfile

import bpy
from bpy.props import EnumProperty, PointerProperty, StringProperty

PREVIEW_SIZE = (256, 112)
CATEGORIES = [('Map', 'Map', ''), ('Character', 'Character', ''), ('Skill', 'Skill', ''),
              ('Animation', 'Animation', ''), ('Music', 'Music', '')]
AGENT = 'phantom-dust-stage-addon'


def _token(context):
    try:
        t = context.preferences.addons[__package__].preferences.github_token
    except (KeyError, AttributeError):
        t = ''
    return (t or os.environ.get('GH_TOKEN') or os.environ.get('GITHUB_TOKEN') or '').strip()


def _safe(text):
    return ''.join(c if c.isalnum() or c in '-_.' else '_' for c in text.strip()) or 'Map'


def _one_line(text):
    return ' '.join(str(text).split())


class PDReleaseSettings(bpy.types.PropertyGroup):
    preview: PointerProperty(type=bpy.types.Image, name='Preview',
                             description='preview.png: shown in the map picker and the Mods list (saved as 256 x 112)')
    mod_id: StringProperty(name='ID', description='mod-info.ini id: a random 32-character hash, made once and kept for '
                                                  'every version of this mod')
    author: StringProperty(name='Author', description='mod author name')
    name: StringProperty(name='Name', description='name of the mod')
    version: StringProperty(name='Version', default='0.1', description='version, e.g. 0.1, 0.25, 1.0, 2.4.1 (also the '
                                                                      'GitHub release tag)')
    desc: StringProperty(name='Description', description='description of the mod (keep it short)')
    category: EnumProperty(name='Category', items=CATEGORIES, options={'ENUM_FLAG'}, default={'Map'},
                           description='category of mod (can be several)')
    file_name: StringProperty(name='Map File', description='Name of the map files in the zip (<name>.alr and .dat); '
                                                           'empty: the mod name')
    folder: StringProperty(name='Output Folder', subtype='DIR_PATH', default='//release',
                           description='Where the release .zip is written')
    repo: StringProperty(name='GitHub Repo', description='owner/repository the release goes to, e.g. '
                                                         'eradication0/phantom-dust-map-aquarium')
    last_zip: StringProperty(name='Last Zip', subtype='FILE_PATH', options={'HIDDEN'})


def settings(context):
    return context.scene.pd_release


def file_base(r):
    return _safe(r.file_name or r.name)


def zip_name(r):
    return '%s.%s.zip' % (_safe(r.name), _safe(r.version))


def ini_text(r, has_preview):
    cats = ','.join(k for k, _n, _d in CATEGORIES if k in r.category) or 'Map'
    return ('; random MD5 hash generated from: https://onlinehashtools.com/generate-random-md5-hash\n'
            '; just grab a random one if this is your first time\n'
            'id=%s\n\n; mod author name\nauthor=%s\n\n; name of the mod\nname=%s\n\n'
            '; version eg: 0.1, 0.25, 1.0, 2.4.1, 0.4.1\nver=%s\n\n'
            '; description of the mod (keep it short)\ndesc=%s\n\n'
            '; category of mod. Possible categories: Map, Character, Skill, Animation, Music \n'
            '; can contain multiple\ncategory=%s\n\n'
            '; display image, name it "preview.png"\n; it should be 256px X 112px in size exactly\npreview=%d\n'
            % (_one_line(r.mod_id), _one_line(r.author), _one_line(r.name), _one_line(r.version), _one_line(r.desc),
               cats, 1 if has_preview else 0))


def read_ini(text):
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if not line or line.startswith(';') or '=' not in line:
            continue
        k, v = line.split('=', 1)
        out[k.strip().lower()] = v.strip()
    return out


def problems(r):
    out = []
    if not r.name.strip():
        out.append('the mod has no name')
    if not r.version.strip():
        out.append('the mod has no version')
    if len(r.mod_id.strip()) < 8:
        out.append('the mod has no id (New ID)')
    if not r.author.strip():
        out.append('the mod has no author')
    return out


def save_preview(img, path):
    """The preview as a 256 x 112 PNG (scaled if it is another size)."""
    cp = img.copy()
    try:
        if tuple(cp.size) != PREVIEW_SIZE:
            cp.scale(*PREVIEW_SIZE)
        cp.filepath_raw = path
        cp.file_format = 'PNG'
        cp.save()
    finally:
        bpy.data.images.remove(cp)


# ---------------------------------------------------------------- operators

class PDSTAGE_OT_release_new_id(bpy.types.Operator):
    """Make a new random mod id (once per mod: keep it for every version, the games know the mod by it)"""
    bl_idname = 'pdstage.release_new_id'
    bl_label = 'New ID'
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        if settings(context).mod_id.strip():
            return context.window_manager.invoke_confirm(self, event, message='Replace the mod id? Every version of '
                                                                            'one mod should keep the same id')
        return self.execute(context)

    def execute(self, context):
        settings(context).mod_id = uuid.uuid4().hex
        return {'FINISHED'}


class PDSTAGE_OT_release_load_ini(bpy.types.Operator):
    """Fill the release fields from an existing mod-info.ini or release .zip (and its preview.png)"""
    bl_idname = 'pdstage.release_load_ini'
    bl_label = 'Load mod-info.ini'
    bl_options = {'REGISTER', 'UNDO'}

    filepath: StringProperty(subtype='FILE_PATH')
    filter_glob: StringProperty(default='*.ini;*.zip', options={'HIDDEN'})

    def invoke(self, context, event):
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        r = settings(context)
        path = bpy.path.abspath(self.filepath)
        preview = None
        try:
            if path.lower().endswith('.zip'):
                with zipfile.ZipFile(path) as z:
                    names = {n.lower(): n for n in z.namelist()}
                    text = z.read(names['mod-info.ini']).decode('utf-8', 'replace')
                    alr = next((n for n in z.namelist() if n.lower().endswith('.alr') and '/' not in n), None)
                    if alr:
                        r.file_name = os.path.splitext(alr)[0]
                    if 'preview.png' in names:
                        preview = z.read(names['preview.png'])
            else:
                text = open(path, encoding='utf-8', errors='replace').read()
                p = os.path.join(os.path.dirname(path), 'preview.png')
                if os.path.isfile(p):
                    preview = open(p, 'rb').read()
        except (OSError, KeyError, zipfile.BadZipFile) as e:
            self.report({'ERROR'}, 'Could not read it: %s' % e)
            return {'CANCELLED'}
        v = read_ini(text)
        r.mod_id = v.get('id', r.mod_id)
        r.author = v.get('author', r.author)
        r.name = v.get('name', r.name)
        r.version = v.get('ver', r.version)
        r.desc = v.get('desc', r.desc)
        cats = {k for k, _n, _d in CATEGORIES for c in v.get('category', '').replace(';', ',').split(',')
                if c.strip().lower() == k.lower()}
        if cats:
            r.category = cats
        if preview:
            tmp = os.path.join(tempfile.mkdtemp(prefix='pd_preview_'), 'preview.png')
            with open(tmp, 'wb') as f:
                f.write(preview)
            img = bpy.data.images.load(tmp)
            img.pack()                                     # kept in the .blend
            r.preview = img
        self.report({'INFO'}, 'Loaded %s %s' % (r.name, r.version))
        return {'FINISHED'}


class PDSTAGE_OT_release_build(bpy.types.Operator):
    """Export this map and pack it with mod-info.ini and preview.png as <Name>.<version>.zip, ready to publish"""
    bl_idname = 'pdstage.release_build'
    bl_label = 'Build Release Zip'

    def execute(self, context):
        r = settings(context)
        bad = problems(r)
        if bad:
            self.report({'ERROR'}, 'Release: ' + '; '.join(bad))
            return {'CANCELLED'}
        from . import exporter
        from .scene_tools import _prefs_game_data
        game_data = bpy.path.abspath(_prefs_game_data(context))
        if not game_data:
            self.report({'ERROR'}, 'Set the game data folder in the add-on preferences')
            return {'CANCELLED'}
        out_dir = bpy.path.abspath(r.folder or '//release')
        if out_dir.startswith('//') or not out_dir:
            self.report({'ERROR'}, 'Save the .blend first, or pick an output folder')
            return {'CANCELLED'}
        os.makedirs(out_dir, exist_ok=True)
        base = file_base(r)
        work = tempfile.mkdtemp(prefix='pd_release_')
        try:
            dat = os.path.join(work, base + '.dat')
            res = bpy.ops.export_scene.phantom_dust_stage(
                'EXEC_DEFAULT', filepath=dat, game_original=context.scene.pd_game_original,
                scale=context.scene.pd_scale, game_data=game_data, install_to_game=False)
            if 'FINISHED' not in res or not os.path.isfile(dat):
                self.report({'ERROR'}, 'The export failed (see its message); no release made')
                return {'CANCELLED'}
            alr = os.path.join(work, base + '.alr')
            if not os.path.isfile(alr):                     # no Visuals: the game original's model goes along
                shutil.copyfile(exporter.game_original_alr(game_data, context.scene.pd_game_original), alr)
            has_preview = r.preview is not None
            if has_preview:
                save_preview(r.preview, os.path.join(work, 'preview.png'))
            path = os.path.join(out_dir, zip_name(r))
            with zipfile.ZipFile(path, 'w', zipfile.ZIP_DEFLATED) as z:
                z.writestr('mod-info.ini', ini_text(r, has_preview).replace('\n', '\r\n'))   # as the community's files
                if has_preview:
                    z.write(os.path.join(work, 'preview.png'), 'preview.png')
                z.write(alr, base + '.alr')
                z.write(dat, base + '.dat')
        except (OSError, RuntimeError) as e:
            self.report({'ERROR'}, 'Release: %s' % e)
            return {'CANCELLED'}
        finally:
            shutil.rmtree(work, ignore_errors=True)
        r.last_zip = path
        self.report({'INFO'}, 'Release built: %s (%.1f MB)%s' % (path, os.path.getsize(path) / 1048576.0,
                                                                  '' if has_preview else '; no preview.png'))
        return {'FINISHED'}


def _api(method, url, token, data=None, content_type='application/json'):
    req = urllib.request.Request(url, data=data, method=method, headers={
        'Accept': 'application/vnd.github+json', 'Authorization': 'Bearer ' + token, 'User-Agent': AGENT,
        'X-GitHub-Api-Version': '2022-11-28', 'Content-Type': content_type})
    with urllib.request.urlopen(req, timeout=600) as resp:
        body = resp.read()
    return json.loads(body) if body else {}


def _error(e):
    try:
        msg = json.loads(e.read()).get('message', '')
    except Exception:
        msg = ''
    return 'GitHub answered %d%s' % (e.code, (': ' + msg) if msg else '')


class PDSTAGE_OT_release_publish(bpy.types.Operator):
    """Publish the built release zip as a new GitHub release (tag = the version) on the mod's repository: Rebirth's
    mod catalog picks it up within minutes"""
    bl_idname = 'pdstage.release_publish'
    bl_label = 'Publish to GitHub'

    def invoke(self, context, event):
        r = settings(context)
        return context.window_manager.invoke_confirm(
            self, event, title='Publish %s %s' % (r.name, r.version),
            message='Create release %s on %s and upload %s? Players get it as an update.'
                    % (r.version, r.repo, os.path.basename(r.last_zip)))

    def execute(self, context):
        r = settings(context)
        token = _token(context)
        repo = r.repo.strip().strip('/')
        if repo.startswith('https://github.com/'):
            repo = repo[len('https://github.com/'):]
        if repo.count('/') != 1:
            self.report({'ERROR'}, 'Set the GitHub repo as owner/repository')
            return {'CANCELLED'}
        if not token:
            self.report({'ERROR'}, 'No GitHub token: add one in the add-on preferences (a fine-grained token with '
                                   'Contents: read and write on %s)' % repo)
            return {'CANCELLED'}
        path = bpy.path.abspath(r.last_zip)
        if not path or not os.path.isfile(path) or os.path.basename(path) != zip_name(r):
            self.report({'ERROR'}, 'Build the release zip for version %s first' % r.version)
            return {'CANCELLED'}
        api = 'https://api.github.com/repos/' + repo
        try:
            try:
                rel = _api('POST', api + '/releases', token, json.dumps(dict(
                    tag_name=r.version, name='%s %s' % (r.name, r.version), body=r.desc or '',
                    draft=False, prerelease=False)).encode())
            except urllib.error.HTTPError as e:
                if e.code == 422:
                    self.report({'ERROR'}, 'Release %s already exists on %s (or the repository is empty): raise the '
                                           'version' % (r.version, repo))
                    return {'CANCELLED'}
                raise
            upload = rel['upload_url'].split('{')[0] + '?name=' + urllib.request.quote(os.path.basename(path))
            with open(path, 'rb') as f:
                data = f.read()
            try:
                _api('POST', upload, token, data, 'application/zip')
            except urllib.error.HTTPError:
                try:                                       # no half release left behind
                    _api('DELETE', api + '/releases/%d' % rel['id'], token)
                except Exception:
                    pass
                raise
        except urllib.error.HTTPError as e:
            self.report({'ERROR'}, 'Publish failed: ' + _error(e))
            return {'CANCELLED'}
        except (urllib.error.URLError, OSError) as e:
            self.report({'ERROR'}, 'Publish failed: %s' % e)
            return {'CANCELLED'}
        url = rel.get('html_url', 'https://github.com/%s/releases' % repo)
        self.report({'INFO'}, 'Published %s' % url)
        try:
            bpy.ops.wm.url_open(url=url)
        except RuntimeError:
            pass
        return {'FINISHED'}


class PDSTAGE_PT_release(bpy.types.Panel):
    bl_label = 'Release'
    bl_space_type = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category = 'Phantom Dust'
    bl_order = 50
    bl_options = {'DEFAULT_CLOSED'}

    def draw(self, context):
        r = settings(context)
        lay = self.layout
        lay.operator(PDSTAGE_OT_release_load_ini.bl_idname, icon='FILE_FOLDER')
        box = lay.box()
        box.label(text='1. Preview (preview.png, 256 x 112)', icon='IMAGE_DATA')
        box.template_ID_preview(r, 'preview', open='image.open', rows=2, cols=4)
        if r.preview is not None and tuple(r.preview.size) != PREVIEW_SIZE:
            box.label(text='%d x %d: scaled to 256 x 112 in the zip' % tuple(r.preview.size), icon='INFO')
        box = lay.box()
        box.label(text='2. mod-info.ini', icon='TEXT')
        row = box.row(align=True)
        row.prop(r, 'mod_id')
        row.operator(PDSTAGE_OT_release_new_id.bl_idname, text='', icon='FILE_REFRESH')
        for k in ('author', 'name', 'version', 'desc'):
            box.prop(r, k)
        box.prop(r, 'category')
        box = lay.box()
        box.label(text='3. Files', icon='PACKAGE')
        box.prop(r, 'file_name', placeholder=file_base(r))
        box.label(text='Zip: %s  (%s.alr, %s.dat)' % (zip_name(r), file_base(r), file_base(r)))
        box.prop(r, 'folder')
        box.operator(PDSTAGE_OT_release_build.bl_idname, icon='EXPORT')
        if r.last_zip:
            box.label(text='Last: ' + os.path.basename(r.last_zip), icon='CHECKMARK')
        box = lay.box()
        box.label(text='4. Publish', icon='URL')
        box.prop(r, 'repo')
        if not _token(context):
            box.label(text='Add a GitHub token in the add-on', icon='ERROR')
            box.label(text='preferences to publish', icon='BLANK1')
        sub = box.column()
        sub.enabled = bool(r.last_zip and r.repo)
        sub.operator(PDSTAGE_OT_release_publish.bl_idname, icon='WORLD')


classes = (PDReleaseSettings, PDSTAGE_OT_release_new_id, PDSTAGE_OT_release_load_ini, PDSTAGE_OT_release_build,
           PDSTAGE_OT_release_publish, PDSTAGE_PT_release)


def register():
    for c in classes:
        old = getattr(bpy.types, c.__name__, None)
        if old is not None:
            try:
                bpy.utils.unregister_class(old)
            except RuntimeError:
                pass
        bpy.utils.register_class(c)
    bpy.types.Scene.pd_release = PointerProperty(type=PDReleaseSettings)


def unregister():
    if hasattr(bpy.types.Scene, 'pd_release'):
        del bpy.types.Scene.pd_release
    for c in reversed(classes):
        try:
            bpy.utils.unregister_class(c)
        except RuntimeError:
            pass
