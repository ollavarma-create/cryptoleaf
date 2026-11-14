from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image

from src import batch_processor as batch


def test_dry_run_does_not_create_outputs(tmp_path):
    src, out = tmp_path / 'input', tmp_path / 'output'
    src.mkdir()
    (src / 'photo.jpg').write_bytes(b'not actually decoded in dry run')
    results = batch.process_batch(src, out, b'secret', 'password', dry_run=True)
    assert [r.status for r in results] == ['DRY_RUN']
    assert not out.exists()


def test_dispatch_and_first_success(tmp_path, monkeypatch):
    src, out = tmp_path / 'input', tmp_path / 'output'
    src.mkdir()
    (src / 'a.jpg').write_bytes(b'original jpeg')
    (src / 'b.png').write_bytes(b'original png')
    calls = []

    def jpeg(cover, output, payload, password, **kwargs):
        calls.append(('JPEG', kwargs['mode']))
        Path(output).write_bytes(b'jpeg output')
        return SimpleNamespace(strength=15, attempts=2, psnr=41.5)

    def lossless(cover, payload, password, *, output_format):
        calls.append(('PNG', output_format))
        return Image.new('RGB', (32, 32)), output_format

    monkeypatch.setattr(batch, 'optimize_jpeg', jpeg)
    monkeypatch.setattr(batch, 'encode_image', lossless)
    monkeypatch.setattr(batch, 'decode_image', lambda path, password: b'secret')
    results = batch.process_batch(src, out, b'secret', 'password')
    assert [r.status for r in results] == ['OK', 'OK']
    assert calls == [('JPEG', 'first_success'), ('PNG', 'PNG')]
    assert (src / 'a.jpg').read_bytes() == b'original jpeg'
    assert (src / 'b.png').read_bytes() == b'original png'
    assert (out / 'b_cryptoleaf.png').exists()


def test_failure_does_not_stop_batch(tmp_path, monkeypatch):
    src, out = tmp_path / 'input', tmp_path / 'output'
    src.mkdir()
    (src / 'a.jpg').write_bytes(b'a')
    (src / 'b.jpg').write_bytes(b'b')

    def jpeg(cover, output, payload, password, **kwargs):
        if cover.name == 'a.jpg':
            raise ValueError('too small')
        Path(output).write_bytes(b'ok')
        return SimpleNamespace(strength=10, attempts=1, psnr=40)

    monkeypatch.setattr(batch, 'optimize_jpeg', jpeg)
    results = batch.process_batch(src, out, b'secret', 'password')
    assert [r.status for r in results] == ['FAIL', 'OK']
    assert not (out / 'a_cryptoleaf.jpg').exists()


def test_existing_output_never_overwritten(tmp_path, monkeypatch):
    src, out = tmp_path / 'input', tmp_path / 'output'
    src.mkdir()
    out.mkdir()
    (src / 'a.jpg').write_bytes(b'original')
    target = out / 'a_cryptoleaf.jpg'
    target.write_bytes(b'preserve')
    results = batch.process_batch(src, out, b'secret', 'password')
    assert results[0].status == 'FAIL'
    assert target.read_bytes() == b'preserve'
    results = batch.process_batch(src, out, b'secret', 'password', skip_existing=True)
    assert results[0].status == 'SKIPPED'
    assert target.read_bytes() == b'preserve'


def test_output_inside_input_is_rejected(tmp_path):
    src = tmp_path / 'input'
    src.mkdir()
    with pytest.raises(ValueError):
        batch.process_batch(src, src / 'output', b'secret', 'password', dry_run=True)


def test_lossless_roundtrip_failure_does_not_publish(tmp_path, monkeypatch):
    src, out = tmp_path / 'input', tmp_path / 'output'
    src.mkdir()
    (src / 'a.png').write_bytes(b'original')
    monkeypatch.setattr(batch, 'encode_image', lambda *args, **kwargs: (Image.new('RGB', (32, 32)), 'PNG'))
    monkeypatch.setattr(batch, 'decode_image', lambda *args: b'wrong')
    results = batch.process_batch(src, out, b'secret', 'password')
    assert results[0].status == 'FAIL'
    assert 'Round-trip' in results[0].error
    assert not (out / 'a_cryptoleaf.png').exists()
    assert not list(out.glob('.cryptoleaf-*'))


def test_real_lossless_roundtrip(tmp_path):
    src, out = tmp_path / 'input', tmp_path / 'output'
    src.mkdir()
    Image.new('RGB', (64, 64), color=(100, 150, 200)).save(src / 'a.png')
    results = batch.process_batch(src, out, b'secret', 'password')
    assert results[0].status == 'OK', results[0].error
    assert batch.decode_image(out / 'a_cryptoleaf.png', 'password') == b'secret'


def test_jpeg_failure_leaves_no_temp_files(tmp_path, monkeypatch):
    src, out = tmp_path / 'input', tmp_path / 'output'
    src.mkdir()
    (src / 'a.jpg').write_bytes(b'original')
    def broken(cover, output, payload, password, **kwargs):
        Path(output).write_bytes(b'partial')
        raise ValueError('failed')
    monkeypatch.setattr(batch, 'optimize_jpeg', broken)
    results = batch.process_batch(src, out, b'secret', 'password')
    assert results[0].status == 'FAIL'
    assert not list(out.iterdir())
