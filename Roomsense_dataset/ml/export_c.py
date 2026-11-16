"""Export Decision Tree เป็น C (micromlgen) แล้วคอมไพล์บนเครื่องเพื่อเทียบผลกับ Python ทุก window ของ test"""
import json, os, pickle, subprocess
import numpy as np
import pandas as pd
from micromlgen import port

obj = pickle.load(open("final_model.pkl", "rb"))
model, F, THR = obj["model"], obj["features"], obj["threshold"]
imp, tree = model[0], model[-1]
os.makedirs("c_export", exist_ok=True)

code = port(tree, classname="PowerModel")
open("c_export/PowerModel.h", "w").write(code)

te = pd.read_csv("windows_test.csv")
X = imp.transform(te[F].values)
py_pred = (model.predict_proba(te[F].values)[:, 1] >= THR).astype(int)
py_predict = tree.predict(X)
np.savetxt("c_export/test_features.csv", X, delimiter=",", fmt="%.6f")

harness = r'''
#include <cstdio>
#include <cstdint>
#include "PowerModel.h"
int main() {
    Eloquent::ML::Port::PowerModel model;
    FILE *f = fopen("test_features.csv", "r");
    float x[%d];
    while (true) {
        int ok = 1;
        for (int i = 0; i < %d; i++) { if (fscanf(f, i ? ",%%f" : "%%f", &x[i]) != 1) { ok = 0; break; } }
        if (!ok) break;
        printf("%%d\n", model.predict(x));
    }
    return 0;
}
''' % (len(F), len(F))
open("c_export/harness.cpp", "w").write(harness)
subprocess.run(["g++", "-O2", "-std=c++11", "-o", "harness", "harness.cpp"], cwd="c_export", check=True)
out = subprocess.run(["./harness"], cwd="c_export", capture_output=True, text=True, check=True).stdout.split()
c_pred = np.array([int(v) for v in out])
subprocess.run(["g++", "-Os", "-c", "-x", "c++", "-std=c++11", "-o", "model.o", "-"], cwd="c_export", check=True,
               input='#include "PowerModel.h"\nfloat f(float*x){Eloquent::ML::Port::PowerModel m;return m.predict(x);}\n',
               text=True)
size = subprocess.run(["size", "model.o"], cwd="c_export", capture_output=True, text=True).stdout

res = dict(n=len(c_pred), match_vs_predict=int((c_pred == py_predict).sum()),
           match_vs_threshold=int((c_pred == py_pred).sum()), header_bytes=len(code),
           object_size=size.strip().splitlines()[-1], features_order=F,
           imputer_medians=dict(zip(F, [float(v) for v in imp.statistics_])))
json.dump(res, open("c_export/verify.json", "w"), ensure_ascii=False, indent=1)
print(json.dumps(res, ensure_ascii=False, indent=1))
print(code)
