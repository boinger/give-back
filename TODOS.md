# TODOs

## output.py size

`output.py` is 764 LOC with 25 functions handling all terminal formatting for
every command. It has tests now (56 in `test_output.py`) but is the largest
file after `cli.py`. High churn (10 changes in 90 days).

Consider splitting into `output/` package by command group (assess, triage,
sniff, conventions, deps) if the file keeps growing. Not urgent — the current
flat structure works fine and the functions are well-namespaced by prefix.
