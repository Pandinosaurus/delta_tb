rm -r ../../__pycache__
rm -r build
mkdir build

echo "############################ different training settings -- all test on potsdam ############################"
echo "supervised color"
/data/anaconda3/bin/python -u train.py POTSDAM_lod0
/data/anaconda3/bin/python -u test.py  POTSDAM_lod0 | tee build/p2pcolor.txt

echo "supervised"
/data/anaconda3/bin/python -u train.py POTSDAM_lod0 normalize
/data/anaconda3/bin/python -u test.py  POTSDAM_lod0 normalize | tee build/p2p.txt

echo "transfert "
/data/anaconda3/bin/python -u train.py AIRS normalize
/data/anaconda3/bin/python -u test.py  POTSDAM_lod0 normalize | tee build/a2p.txt

/data/anaconda3/bin/python -u train.py VAIHINGEN_lod0 normalize
/data/anaconda3/bin/python -u test.py  POTSDAM_lod0 normalize | tee build/v2p.txt


rm -r ../../__pycache__
