"""Run with the CAD environment: python -m unittest discover -s tests -p test_calibration_geometry.py."""
import importlib.util
import math
import tempfile
import unittest
from pathlib import Path

@unittest.skipUnless(importlib.util.find_spec('cadquery'),'Requires the separate CAD environment')
class CouponGeometryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        import trimesh
        from printflow.calibration_geometry import generate_coupon
        from printflow.calibration_catalog import TESTS
        Path('.runtime').mkdir(exist_ok=True)
        cls.directory=tempfile.TemporaryDirectory(prefix='calibration-geometry-',dir=Path('.runtime').resolve())
        cls.meshes={}
        for t in TESTS:
            if t['mode']!='coupon':continue
            path=Path(cls.directory.name)/(t['id']+'.stl');generate_coupon(t['id'],path);cls.meshes[t['id']]=trimesh.load(path,force='mesh',process=True)
    @classmethod
    def tearDownClass(cls):cls.directory.cleanup()
    def test_all_coupon_meshes_are_closed_oriented_and_fit_the_bed(self):
        for key,m in self.meshes.items():
            with self.subTest(key=key):
                self.assertTrue(m.is_watertight);self.assertTrue(m.is_winding_consistent);self.assertGreater(m.volume,0)
                self.assertLessEqual(max(m.extents),101);self.assertGreaterEqual(min(m.bounds[0]),-.01)
    def test_overhang_face_angles_match_the_declared_vertical_reference(self):
        angles={round(math.degrees(math.atan(abs(n[2]/n[1])))) for n in self.meshes['overhang'].face_normals if abs(n[0])<1e-5 and abs(n[1])>.01 and abs(n[2])>.01}
        self.assertEqual(angles,{35,45,55,65,75})
    def test_patches_are_one_layer_and_clearance_pin_is_separate(self):
        patch=self.meshes['first_layer'];self.assertAlmostEqual(patch.extents[2],.2,places=5)
        self.assertEqual(len(patch.split()),5);self.assertEqual(len(self.meshes['clearance'].split()),2)
        self.assertEqual(len(self.meshes['bridges'].split()),5)
    def test_dimensional_block_has_two_nominal_holes(self):
        m=self.meshes['dimensions'];self.assertTrue(all(abs(x-20)<.01 for x in m.extents))
        self.assertAlmostEqual(m.volume,20**3-math.pi*(2.5**2+5**2)*20,delta=2)

if __name__=='__main__':unittest.main()
