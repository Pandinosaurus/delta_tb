rm -r ../__pycache__
rm -r build
mkdir build

/data/anaconda3/bin/python -u vaihingen_train.py | tee build/vaihingen_train.txt
/data/anaconda3/bin/python -u vaihingen_test.py  | tee build/vaihingen_test.txt

rm -r ../__pycache__
