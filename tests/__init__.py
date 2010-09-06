import os
import glob
import unittest

def test_suite():
    def find_tests():
        basedir = os.path.realpath(os.path.dirname(__file__))
        for filename in glob.glob(os.path.join(basedir, 'test_*.py')):
            yield 'tests.%s' % os.path.splitext(os.path.basename(filename))[0]
    tests = unittest.TestLoader().loadTestsFromNames(find_tests())
    suite = unittest.TestSuite()
    suite.addTests(tests)
    return suite
