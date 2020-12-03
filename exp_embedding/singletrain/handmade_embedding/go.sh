rm -r ../../__pycache__
rm -r build
mkdir build

/data/anaconda3/bin/python -u train.py VAIHINGEN BRUGES POTSDAM | tee build/vbp2vbp_train.txt
/data/anaconda3/bin/python -u test.py  VAIHINGEN BRUGES POTSDAM | tee build/vbp2vbp_test.txt

/data/anaconda3/bin/python -u train.py VAIHINGEN_all BRUGES_all | tee build/vb2p_train.txt
/data/anaconda3/bin/python -u test.py  POTSDAM_all | tee build/vb2p_test.txt

rm -r ../../__pycache__
