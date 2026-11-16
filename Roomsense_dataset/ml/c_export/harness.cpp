
#include <cstdio>
#include <cstdint>
#include "PowerModel.h"
int main() {
    Eloquent::ML::Port::PowerModel model;
    FILE *f = fopen("test_features.csv", "r");
    float x[7];
    while (true) {
        int ok = 1;
        for (int i = 0; i < 7; i++) { if (fscanf(f, i ? ",%f" : "%f", &x[i]) != 1) { ok = 0; break; } }
        if (!ok) break;
        printf("%d\n", model.predict(x));
    }
    return 0;
}
