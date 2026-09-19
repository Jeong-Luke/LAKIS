import hashlib, json, os, tempfile, unittest, zipfile
from pathlib import Path
from unittest import mock
import rc_patch


def sha(data): return hashlib.sha256(data).hexdigest().upper()


class RCPatcherTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)/"install"; (self.root/"ComfyUI"/"LAKIS"/"external_ui").mkdir(parents=True)
        (self.root/"LAKIS.exe").write_bytes(b"exe"); (self.root/"VERSION").write_text("7.3.6",encoding="utf-8")
        self.old=self.root/"ComfyUI"/"LAKIS"/"external_ui"/"app.js"; self.old.write_bytes(b"old")
        self.keep=self.root/"ComfyUI"/"LAKIS"/"external_ui"/"retired.js"; self.keep.write_bytes(b"restore me")
    def tearDown(self): self.tmp.cleanup()
    def package(self,name="patch.zip",path="ComfyUI/LAKIS/external_ui/app.js",data=b"new",delete=None,base="7.3.6",hash_value=None,extra=None):
        z=Path(self.tmp.name)/name; m={"format":rc_patch.FORMAT,"display_version":"v7.4.0 RC1","internal_version":"7.3.99.1","base_version":base,"files":[{"path":path,"sha256":hash_value or sha(data),"size":len(data)}],"delete":delete or [],"base_hashes":[{"path":"ComfyUI/LAKIS/external_ui/app.js","sha256":sha(b"old")}]}
        with zipfile.ZipFile(z,"w") as a:
            a.writestr("patch_manifest.json",json.dumps(m)); a.writestr("payload/"+path,data)
            for n,v in extra or []: a.writestr(n,v)
        return z
    def blocked(self,z,needle):
        with self.assertRaises(Exception) as c: rc_patch.apply(z,self.root)
        self.assertIn(needle,str(c.exception).lower())
    def test_valid_and_rollback(self):
        z=self.package(delete=["ComfyUI/LAKIS/external_ui/retired.js"]); rc_patch.apply(z,self.root)
        self.assertEqual(self.old.read_bytes(),b"new"); self.assertFalse(self.keep.exists())
        rc_patch.rollback(self.root); self.assertEqual(self.old.read_bytes(),b"old"); self.assertEqual(self.keep.read_bytes(),b"restore me")
    def test_wrong_base(self): self.blocked(self.package(base="7.3.4"),"wrong base")
    def test_base_hash(self): self.old.write_bytes(b"custom"); self.blocked(self.package(),"base hash mismatch")
    def test_payload_hash(self): self.blocked(self.package(hash_value="0"*64),"payload hash mismatch")
    def test_traversal(self): self.blocked(self.package(path="../escape.txt"),"unsafe")
    def test_absolute(self): self.blocked(self.package(path="C:/escape.txt"),"drive")
    def test_protected_payload(self): self.blocked(self.package(path="ComfyUI/models/x.safetensors"),"protected")
    def test_protected_delete(self): self.blocked(self.package(delete=["ComfyUI/output/a.png"]),"protected")
    def test_malformed(self):
        z=Path(self.tmp.name)/"bad.zip"; zipfile.ZipFile(z,"w").writestr("patch_manifest.json","{"); self.blocked(z,"malformed")
    def test_partial_failure_rolls_back(self):
        z=self.package(); real=rc_patch.os.replace
        def fail(src,dst):
            real(src,dst); raise OSError("simulated post-copy failure")
        with mock.patch.object(rc_patch.os,"replace",side_effect=fail):
            with self.assertRaises(OSError): rc_patch.apply(z,self.root)
        self.assertEqual(self.old.read_bytes(),b"old")
        self.assertFalse((self.root/rc_patch.STATE_DIR/"backups"/"7.3.99.1").exists())


if __name__=="__main__": unittest.main(verbosity=2)
