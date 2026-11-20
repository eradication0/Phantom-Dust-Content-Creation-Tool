"""The readers/writers live inside the add-on (addon/phantom_dust_stage/pdstage), so every way of installing
it, including GitHub's source-code zip, carries them. This package points there, so tools and tests can keep
using `from pdstage import dat` from the repository root."""
import os

__path__ = [os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'addon', 'phantom_dust_stage', 'pdstage')]
