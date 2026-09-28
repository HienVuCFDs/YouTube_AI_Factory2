# UI cleanup feature map

Muc tieu: UI gon hon nhung khong lam mat tinh nang. Moi tinh nang van co cho dung cua no: nut chinh nam tren happy path, tuy chon nang cao nam trong khoi thu gon, job/log/preflight nam o panel trang thai.

## 1. Nguon

Chuc nang can co:
- Tao project tu topic.
- Tao project tu video YouTube.
- Tao project tu link bat ky ma yt-dlp doc duoc.
- Tao project tu file local da upload.
- Tao project tu anh, bo anh hoac folder anh.
- Tao project tu bai bao/URL bai viet hoac text da dan.
- Chon workflow: Content, Reup, Anh to Video, Bao to Video.
- Chon ngon ngu dau ra, ty le khung hinh, nen tang xuat ban.
- Kiem tra quyen/tinh hop le cua nguon truoc khi san xuat.

Nut chinh:
- Tao project / Tiep tuc phan tich.

Nang cao:
- Cookie file cho site can dang nhap.
- Kenh workflow tham khao.
- Ho so output: YouTube ngang, Shorts, TikTok, Reels, square.

## 2. Phan tich

Chuc nang can co:
- Doc metadata.
- Lay transcript co san neu co.
- Whisper local tu audio/file neu can.
- Phan tich noi dung, cau truc, nhan vat, su kien, claim, nhac do/nhan dien.
- Phan tich reference style neu dung video/kienh mau.
- Duyet ket qua phan tich truoc khi viet.

Nut chinh:
- Phan tich nguon.

Nang cao:
- Chon AI phan tich: local, Codex, Claude Code, Antigravity, OpenAI/Anthropic API neu co.
- Gioi han chi phi/token.
- Chon che do: tom tat nhanh / phan tich sau.

## 3. Kich ban

Chuc nang can co:
- AI viet kich ban moi.
- Dan kich ban co san.
- Chat chinh sua kich ban.
- Luu version.
- So sanh version.
- Duyet kich ban.
- Tao kich ban Short rieng.
- Dich/ngon ngu hoa loi doc.
- Kiem tra fidelity cho WF Reup.

Nut chinh:
- Viet kich ban / Duyet kich ban.

Nang cao:
- Chon AI viet.
- Do dai muc tieu.
- Giong dieu.
- Cau truc mo dau, than bai, CTA.
- Ap dung yeu cau cho video dai, Short, hoac ca hai.

## 4. Giong doc

Chuc nang can co:
- Chon provider voice.
- Chon giong/model.
- Nghe thu.
- Tao voice cho tat ca canh.
- Tao lai voice tung canh.
- Upload/gap voice thu cong tung canh.
- Gan lai voice da tao neu timeline bi tao lai.
- AI/nghe lai bang Whisper de kiem tra voice co doc dung loi khong.
- Tao voice Short.

Nut chinh:
- Luu cau hinh voice / Tao giong doc.

Nang cao:
- Toc do doc.
- Voice sample.
- Provider phu de.
- Whisper model neu nghe lai audio.

## 5. Storyboard

Chuc nang can co:
- Tao storyboard tu kich ban.
- Timeline preview bar tren dau.
- Click vao canh tren timeline de scroll/focus card.
- Play preview tung canh.
- Play storyboard draft tu cac asset da co.
- Sua loi doc tung canh.
- Sua visual prompt tung canh.
- Sua thoi luong tung canh.
- Chon visual kind: source clip, image, gif, video, stock footage, motion graphics, fallback.
- Chon provider theo tung canh.
- Tao anh/video tung canh.
- Tao anh/video batch cho canh thieu.
- Upload/gap asset thu cong.
- Retry/huy job tung canh.
- Edit plan draft -> approve -> apply.
- Preflight: thieu voice, thieu visual, provider chua san sang, job dang chay, scene loi.

Nut chinh:
- Tao storyboard / Kiem tra truoc khi dung / Tao phan con thieu.

Nang cao:
- AI lap storyboard/edit plan.
- AI tao anh mac dinh.
- AI tao video mac dinh.
- Motion policy.
- Fallback policy.
- Cleanup logo/subtitle cho WF Reup.

## 6. Xuong dung

Chuc nang can co:
- Render preview nhanh.
- Render video dai.
- Render Short.
- Chon engine FFmpeg/OpenMontage/Remotion neu san sang.
- Chon output profile.
- Gan nhac nen.
- Chuyen canh, subtitle burn-in, cleanup marks.
- Quality check truoc render va sau render.
- Xem job, log, retry, cancel.
- Xuat goi Premiere.

Nut chinh:
- Render ban nhap / Render final.

Nang cao:
- GPU/NVENC.
- Bitrate, FPS, fit pad/cover.
- Subtitle style.
- Music volume.

## 7. Xuat ban

Chuc nang can co:
- Tao title, description, hashtag.
- Thumbnail.
- Checklist publish.
- Upload tay package.
- Upload YouTube neu OAuth san sang.
- Dang Shorts/Reels/TikTok/Facebook ve sau.
- Duyet cuoi bat buoc.

Nut chinh:
- Tao goi xuat ban / Dang sau khi duyet.

Nang cao:
- Lich dang.
- Playlist.
- Privacy.
- Platform copy theo tung nen tang.

## Nguyen tac khong mat tinh nang

- Moi tinh nang hien co duoc gan vao mot buoc ro rang.
- Tinh nang hay dung nam ngoai man hinh chinh.
- Tinh nang hiem dung, beta, can cau hinh nam trong details "Nang cao".
- Nut khong chay duoc phai hien ly do khoa, khong de trong im lang.
- Moi nut ton credit, tai nguon, render lau, hoac publish phai co preflight/confirm.
