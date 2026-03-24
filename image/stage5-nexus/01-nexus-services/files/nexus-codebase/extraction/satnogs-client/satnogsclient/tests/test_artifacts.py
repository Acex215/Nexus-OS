from satnogsclient.artifacts import Artifacts

WATERFALL_DATA = {
    'compressed': {
        'offset': [-80.0, -80.0, -80.0],
        'scale': [0.08, 0.08, 0.08],
        'values': [[25, 25, 40], [25, 25, 40], [25, 25, 40], [25, 25, 40]],
    },
    'trel': [0.0, 1.75, 3.5, 5.25],
    'data': {
        'tabs': [10000, 12000, 14000, 16000],
    },
    'freq': [-24.0, 0.0, 24.0],
}
WATERFALL_METADATA = {
    'timestamp': '2021-10-16T08:16:01.713927Z',
}
METADATA = {
    'observation_id': 4869579,
    'tle': 'LUME-1\n'
    '1 43908U 18111AJ  21288.68382576  .00003429  00000-0  13231-3 0  9993\n'
    '2 43908  97.2165 179.4783 0018756 221.2562 138.7261 15.26798079156017\n',
    'frequency': 437060000,
    'location': {
        'latitude': 36.97059,
        'longitude': 22.14474,
        'altitude': 5
    }
}


# Mock Waterfall object
class Waterfall:

    def __init__(self, _data, _metadata):
        self.data = _data
        self.metadata = _metadata


def test_artifacts():
    artifact = Artifacts(Waterfall(WATERFALL_DATA, WATERFALL_METADATA), METADATA)
    artifact.create()

    # NOTE: Ideally the created file is checked here.
