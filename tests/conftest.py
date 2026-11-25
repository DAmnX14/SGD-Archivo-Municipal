import os
import sys
import tempfile

# Carpeta de datos aislada para las pruebas (debe definirse antes de importar database)
os.environ["SGD_DATOS"] = tempfile.mkdtemp(prefix="sgd_test_")
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
