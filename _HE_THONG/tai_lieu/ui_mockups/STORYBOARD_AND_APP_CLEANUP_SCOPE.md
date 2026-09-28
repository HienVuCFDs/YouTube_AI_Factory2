# Pham vi don UI moi

Quyet dinh: cac buoc san xuat khac nhin chung on. Khong can lam lai toan bo wizard. Tap trung vao 2 diem:

1. Storyboard chua on.
2. Giao dien tong cua app dang qua lang nhang.

## A. Giu nguyen cac buoc dang on

Khong doi logic chinh cua:
- Nguon.
- Phan tich.
- Kich ban.
- Giong doc.
- Xuong dung/render.
- Xuat ban.

Chi don nhe neu can:
- Gop nut phu vao "Nang cao".
- Doi ten nut/label cho de hieu.
- Hien ly do khoa nut neu chua du dieu kien.

## B. Sua man Storyboard thanh "mini editor"

Storyboard phai tra loi duoc 5 cau hoi ngay tren mot man:
- Canh nao da san sang?
- Canh nao thieu hinh?
- Canh nao thieu voice?
- Canh nao dang co job chay/loi?
- Bam dau de sua va preview rieng canh do?

### B1. Thanh timeline tren dau Storyboard

Them mot thanh timeline ngay tren danh sach card canh:
- Moi block = mot canh, do rong theo thoi luong.
- Mau theo trang thai: ready, missing visual, missing voice, fallback, running, error.
- Click block de focus card canh.
- Hover hien: ten canh, thoi luong, provider, trang thai.
- Playhead khi preview.
- Nut: Play storyboard draft, Stop, Preview canh dang chon, Render ban nhap.

### B2. Card canh gon lai nhung manh hon

Moi card canh gom:
- Preview visual.
- Loi doc dang dung de tao voice.
- Audio player/waveform neu co.
- Visual prompt.
- Trang thai scene/job.
- Cac nut nhanh: Sua, Tao lai voice, Tao visual, Gan file, Preview.

Chi tiet nang cao dat trong details:
- Chon image provider cho canh nay.
- Chon video provider cho canh nay.
- Chon visual kind.
- Trim/crop/cleanup.
- Retry/huy job.

### B3. Bang "Thiet lap Storyboard" rieng

Dat o tren hoac ben phai:
- AI lap storyboard/edit plan.
- AI tao anh mac dinh.
- AI tao video mac dinh.
- Motion policy.
- Fallback policy.
- Ty le khung hinh.

Nguyen tac: model/provider khong duoc bien mat. Neu thu gon thi van co summary ro rang, vi du:
"Storyboard: Codex CLI | Anh: ChatGPT web | Video: gflow-cli | Motion: Can bang"

### B4. Preflight live

O ben phai Storyboard:
- Tong so canh.
- So canh san sang.
- Thieu visual.
- Thieu voice.
- Job dang chay.
- Job loi.
- Provider chua san sang.

Nut xu ly:
- Tao phan con thieu.
- Dung fallback ban nhap.
- Mo job/log.
- Kiem tra truoc khi render.

### B5. Che do Reup va Content khac nhau ro

WF Content:
- Hien nut tao anh/video AI, stock footage, motion graphics.

WF Reup:
- Hien nut tai nguon, cat theo loi thoai, xuat source clip, cleanup logo/phu de.
- An cac nut tao AI image/video khoi luong chinh, chi de trong tuy chon neu nguoi dung co chu y muon thay canh.

## C. Don giao dien tong cua app

Muc tieu: nguoi dung mo app len khong bi ngop.

### C1. Sidebar theo nhom

Giu 5 muc chinh:
- Tao video.
- Du an.
- Workflow.
- Dieu phoi AI.
- Cai dat.

An bot cac panel ky thuat khoi man hinh chinh, dua vao dung tab.

### C2. Moi man chi co mot hanh dong chinh

Moi workspace co mot nut chinh noi bat:
- Tao video: tiep tuc buoc dang lam.
- Du an: mo/sua project.
- Workflow: dung workflow nay.
- Dieu phoi AI: bat dau pipeline.
- Cai dat: kiem tra ket noi.

Nut phu dua vao menu/khoi nang cao.

### C3. Beta/can cau hinh khong nam ngang hang voi chuc nang on dinh

Gan nhan:
- San sang.
- Beta.
- Can cau hinh.
- Chua nghiem thu.

Neu chua san sang, hien ly do va nut mo cai dat/job/log lien quan.

### C4. Status panel dung chung

Ben phai hoac tren dau moi workspace co status ngan:
- Project hien tai.
- Buoc hien tai.
- Viec can lam tiep.
- Loi chan.
- Job dang chay.

Khong can nguoi dung mo nhieu panel moi biet app dang ket o dau.

## Thu tu lam

1. Doi Storyboard toolbar thanh "Thiet lap Storyboard" ro rang.
2. Them timeline preview bar.
3. Rut gon card canh, dua tuy chon nang cao vao details.
4. Them preflight live va nut xu ly phan con thieu.
5. Don sidebar/workspace tong: an panel thua, gom beta/cau hinh vao dung cho.
6. Sau khi Storyboard on, moi tinh toi auto pipeline/Telegram.
