# Experiment 1 - crawler implementations (paper Table II): distribution shapes

![Distributions](distributions.png)

| configuration | n | outliers | skewness | excess kurtosis | normality p | shape |
|---|---|---|---|---|---|---|
| process | 60 | 7 | +1.41 | +1.14 | 3.19e-04 | Non-Gaussian: right-skewed, heavy-tailed |
| thread | 60 | 9 | +1.47 | +1.45 | 1.75e-04 | Non-Gaussian: right-skewed, heavy-tailed |
| event | 60 | 8 | +1.87 | +2.60 | 2.03e-06 | Non-Gaussian: right-skewed, heavy-tailed |
