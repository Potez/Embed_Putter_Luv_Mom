#pragma once
#include <cstdarg>
namespace Eloquent {
    namespace ML {
        namespace Port {
            class PowerModel {
                public:
                    /**
                    * Predict class for features vector
                    */
                    int predict(float *x) {
                        if (x[6] <= 35.0) {
                            if (x[5] <= 0.05833333544433117) {
                                return 1;
                            }

                            else {
                                return 1;
                            }
                        }

                        else {
                            if (x[6] <= 75.0) {
                                return 0;
                            }

                            else {
                                return 0;
                            }
                        }
                    }

                protected:
                };
            }
        }
    }