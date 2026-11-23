"""Burst night stacker (HDR+/Hasinoff-style, simplified): ECC align -> kappa-sigma-clipped mean -> NLM denoise -> tone curve.
usage: python nightstack.py <dir> <out.jpg> [rot_ccw_deg]"""
import sys, glob, numpy as np, cv2

d, out = sys.argv[1], sys.argv[2]
rot = int(sys.argv[3]) if len(sys.argv) > 3 else 0
fs = sorted(glob.glob(d + '/*.jpg'))
imgs = [cv2.imread(f, cv2.IMREAD_COLOR | cv2.IMREAD_IGNORE_ORIENTATION).astype(np.float32) for f in fs]
sc = 0.25
small = [cv2.GaussianBlur(cv2.cvtColor(cv2.resize(i, None, fx=sc, fy=sc), cv2.COLOR_BGR2GRAY), (0, 0), 1.5) for i in imgs]
sharp = [cv2.Laplacian(s, cv2.CV_32F).var() for s in small]
ref = int(np.argmax(sharp))
print('frames', len(imgs), 'ref', fs[ref])
h, w = imgs[0].shape[:2]
aligned, used = [], 0
crit = (cv2.TERM_CRITERIA_EPS | cv2.TERM_CRITERIA_COUNT, 100, 1e-5)
for k, im in enumerate(imgs):
    if k == ref:
        aligned.append(im); used += 1; continue
    M = np.eye(2, 3, dtype=np.float32)
    try:
        cc, M = cv2.findTransformECC(small[ref], small[k], M, cv2.MOTION_EUCLIDEAN, crit, None, 5)
    except cv2.error:
        print('skip (no convergence)', fs[k]); continue
    if cc < 0.5:
        print('skip (low corr %.2f)' % cc, fs[k]); continue
    M[:, 2] /= sc
    aligned.append(cv2.warpAffine(im, M, (w, h), flags=cv2.INTER_LINEAR + cv2.WARP_INVERSE_MAP, borderMode=cv2.BORDER_REFLECT))
    used += 1
A = np.stack(aligned)
print('aligned frames', used)
m, s = A.mean(0), A.std(0) + 1e-3
for _ in range(2):  # kappa-sigma clipping
    ok = np.abs(A - m) <= 2.5 * s
    n = np.maximum(ok.sum(0), 1)
    m = (A * ok).sum(0) / n
    s = np.sqrt((((A - m) ** 2) * ok).sum(0) / n) + 1e-3
res = np.clip(m, 0, 255).astype(np.uint8)
res = cv2.fastNlMeansDenoisingColored(res, None, 4, 4, 7, 21)
f = res.astype(np.float32) / 255
lo, hi = np.percentile(f, 0.5), np.percentile(f, 99.7)
f = np.clip((f - lo) / max(hi - lo, 1e-3), 0, 1) ** 0.6
lab = cv2.cvtColor((f * 255).astype(np.uint8), cv2.COLOR_BGR2LAB)
lab[..., 0] = cv2.createCLAHE(2.0, (8, 8)).apply(lab[..., 0])
res = cv2.cvtColor(lab, cv2.COLOR_LAB2BGR)
for _ in range(rot // 90 % 4):
    res = cv2.rotate(res, cv2.ROTATE_90_COUNTERCLOCKWISE)
cv2.imwrite(out, res, [cv2.IMWRITE_JPEG_QUALITY, 95])
print('wrote', out, res.shape, 'mean in/out', float(np.mean(imgs[ref])), float(res.mean()))
