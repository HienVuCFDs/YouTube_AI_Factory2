# Ke hoach nang cap Storyboard va don UI tong

Ngay lap: 2026-09-12; cap nhat quyet dinh: 2026-09-18

Pham vi da chot:
- Hai workflow hien tai uu tien MOT video goc chinh de tao video moi tuong tu hoac dung lai voi kich ban moi. Cho phep them clip nguon phu khi nguoi dung cung cap; chua can tim kiem canh tren nhieu clip.
- Tat ca workflow dung chung mot luong san xuat: Nguon -> Phan tich -> Kich ban -> Giong doc -> Storyboard -> Dung -> Xuat ban.
- Diem can sua sau nhat la Storyboard: lap ke hoach dung, ap dung ke hoach, tao them frame/anh/clip de video moi khac video goc nhung van giu ADN noi dung.
- Giao dien tong cua app can gon lai, bot phoi het moi panel/nut ky thuat.

Luu y phap ly/san pham:
- App khong duoc hua "tranh ban quyen" tuyet doi.
- Muc tieu dung la ho tro tao noi dung co bien doi that: them loi binh, goc nhin, cau truc dung moi, visual moi, overlay, motion graphics, stock/AI visual va dau vet kiem tra.

## Nguyen tac thiet ke

1. AI-first, co diem duyet
   - AI tu phan tich nguon, viet/lap lai kich ban, lap ke hoach tung canh, chon visual, nhip dung, chu/do hoa va tu kiem tra ban nhap.
   - Nguoi dung duyet/phan hoi ke hoach va video; can thiep theo canh khi can. Cong bo va chi phi ben ngoai can hien ro truoc khi chay.

2. Automation-ready
   - UI thu cong va automation sau nay dung chung API/job/state.
   - Telegram, ChatGPT app, Claude app sau nay chi goi lai cac action ma UI da co.

3. Khong mat tinh nang
   - Khong xoa tinh nang dang co.
   - Tinh nang hay dung nam tren luong chinh.
   - Tinh nang nang cao/beta/can cau hinh nam trong details hoac panel rieng.

4. Storyboard la ban dung cua AI
   - Storyboard khong chi la danh sach canh.
   - Hien edit plan, preview, trang thai asset, ly do chon visual va phan hoi theo canh. Timeline la du lieu noi bo de render, khong phat trien bo cong cu cat ghep thu cong kieu NLE.

## Ket qua mong muon

Sau khi lam xong:
- Mo Storyboard len nhin ngay duoc canh nao san sang, canh nao thieu voice/visual, job nao dang chay/loi.
- AI co VisualBeatPlan theo tung canh: asset chinh, nhip cat, chu/do hoa, moc vao/giu/ra, preset hieu ung, vi tri, ly do.
- Co preview dong bo loi doc, hinh, subtitle va do hoa; nguoi dung co the yeu cau AI sua tung canh.
- Co the preview storyboard draft truoc khi render final.
- Co the lap ke hoach bien doi visual cho WF Reup de giu ADN noi dung nhung giam phu thuoc vao visual goc.
- Co the sua yeu cau tung canh: loi doc, prompt, thoi luong, visual kind, provider, asset; AI tao lai ke hoach dung va phan canh bi anh huong.
- Nut "Ap dung ke hoach" tao ra derived timeline/job ro rang, khong im lang sua lung tung.
- Giao dien tong bot roi: sidebar gon, moi workspace co hanh dong chinh, panel ky thuat lui vao dung noi.

## Bo sung tu vi du Reels: do hoa theo tung canh

- Ba anh tham chieu the hien: talking head voi so do/icon va bong hoi, tieu de neon xuat hien, nhan chu tren nen brush. Giao dien Facebook/Messenger nam ngoai khung video thanh pham va khong phai thanh phan can tao lai.
- AI Director chon visual beat theo noi dung loi doc va phong cach canh. Neu can giai thich quy trinh thi dung callout/so do; canh hook co title; canh dan chung co label. Khong ap mot mau chu cho moi canh.
- Moi lop do hoa co `kind`, `text` hoac asset, `style`, `animation`, `position`, `start_seconds`, `end_seconds`, `reason`. Dong bo voi am thanh, giu vung an toan cho mat nguoi va subtitle.
- Registry dung deterministic de render preset duoc phep: giai doan dau title/callout/label/text voi fade, pop, slide_up va clean/neon/card. Sau do them speech bubble, icon flow, brush label, mask/occlusion va motion graphic phuc tap. AI khong tu chen cau lenh FFmpeg.
- Ban nhap va final phai dung cung metadata/preset. QC can kiem tra chu qua dai, nam ngoai khung, de mat/phu de, timing, font tieng Viet va do ro tren dien thoai.
- Tieu chi nghiem thu: tao video tu mot nguon chinh; mot canh talking-head co title hien/giu/bien mat dung loi doc; mot canh co callout/do hoa; AI phan biet phong cach giua canh; nguoi dung yeu cau sua va AI render lai canh do. Cac thanh phan so do/brush phuc tap chi duoc danh dau dat khi da co render va QC thuc te.

## Giai doan 1 - Chuan hoa du lieu ke hoach dung

Muc tieu:
- Them lop du lieu "visual transform plan" cho tung canh.
- Tach ro ke hoach nhap/draft voi timeline dang dung de render.

Backend can lam:
- Mo rong edit plan hien co de moi scene co cac truong:
  - `segment_id`
  - `segment_index`
  - `content_dna`
  - `source_dependency`
  - `visual_strategy`
  - `visual_kind`
  - `provider`
  - `transform_actions`
  - `required_assets`
  - `overlays` (VisualBeatPlan v1: kind/text/style/animation/position/start_seconds/end_seconds/reason)
  - `cleanup_actions`
  - `risk_level`
  - `reason`
- Dinh nghia `visual_strategy`:
  - `source_clip_short`
  - `source_freeze_frame`
  - `ai_image`
  - `ai_video_from_image`
  - `stock_footage`
  - `motion_graphics`
  - `text_card`
  - `map_chart`
  - `manual_asset`
  - `fallback_draft`
- Dinh nghia `source_dependency`:
  - `none`
  - `low`
  - `medium`
  - `high`
- Them version/fingerprint de biet plan co stale khi storyboard/timeline doi.

Frontend can lam:
- Chua doi UI lon, chi dam bao render duoc cac truong moi trong panel ke hoach.

Test can lam:
- Test tao plan co du truong moi.
- Test stale khi timeline/shot thay doi.
- Test draft khong lam doi timeline cho den khi apply.

## Giai doan 2 - Sua AI lap ke hoach bien doi visual

Muc tieu:
- AI khong chi chon transition/effect, ma phai de xuat cach bien doi visual cua tung canh.

Backend can lam:
- Sua prompt `plan_project_edit`:
  - WF Reup: giu nhan vat, su kien, thu tu, cam xuc, so lieu; de xuat visual moi de giam viec dung clip goc dai.
  - WF Content: chon giua AI image/video, stock footage, motion graphics theo tinh chat canh.
  - Anh to Video: giu anh goc lam asset chinh, de xuat motion/crop/transition.
  - Bao to Video: bien y chinh thanh visual stock/motion graphics/text card, tranh bia hinh khong co can cu.
- Bat AI tra ve danh sach canh co:
  - ADN noi dung can giu.
  - Cach visual se khac nguon.
  - Asset can tao them.
  - Ly do chon chien luoc.
  - Muc rui ro neu con qua giong nguon.
- Neu AI loi, fallback deterministic:
  - Reup: uu tien source clip ngan + freeze frame + overlay + stock/motion.
  - Content: image + light motion.

Frontend can lam:
- Hien summary plan:
  - Bao nhieu canh dung source.
  - Bao nhieu canh tao moi.
  - Bao nhieu canh can job.
  - Canh nao rui ro cao.

Test can lam:
- Test WF Reup plan khong mac dinh tat ca canh la source clip.
- Test `gif_only`/motion policy van duoc ton trong.
- Test provider duoc luu va dung dung khi tao job.

## Giai doan 3 - Nut Apply ke hoach dung that

Muc tieu:
- Apply ke hoach phai tao thay doi co y nghia: gan strategy vao timeline, tao job/asset missing, cap nhat visual kind/provider/risk.

Backend can lam:
- Sua endpoint apply:
  - Chi apply plan da approved.
  - Cap nhat timeline fields:
    - `visual_kind`
    - `visual_strategy`
    - `visual_provider`
    - `source_dependency`
    - `risk_level`
    - `edit_transition`
    - `edit_effect`
    - `edit_cleanups`
    - `edit_note`
  - Tao danh sach `required_jobs`; AI tu xep va chay trong gioi han chi phi/quyen da duoc cau hinh. Yeu cau duyet tai diem vuot nguong hoac xuat ban.
- Them endpoint:
  - `GET /api/projects/{project_id}/storyboard/preflight`
  - `POST /api/projects/{project_id}/storyboard/jobs`
  - `POST /api/projects/{project_id}/storyboard/render-draft`
- Preflight tra ve:
  - `can_preview`
  - `can_render_final`
  - `missing_visual`
  - `missing_voice`
  - `high_risk_source_scenes`
  - `provider_blocks`
  - `running_jobs`
  - `failed_jobs`

Frontend can lam:
- Sau khi apply, UI hien "ke hoach da ap dung" va danh sach viec can tao.
- Nut "Tao phan con thieu" dua cac job can thiet vao queue.
- Hien uoc tinh chi phi va ngan sach; khong vuot ngan sach da cau hinh neu chua duyet.

Test can lam:
- Test apply tao required_jobs dung.
- Test job tu chay trong ngan sach va dung tai diem can duyet.
- Test preflight bao dung scene thieu.

## Giai doan 4 - Preview va phan hoi AI trong Storyboard

Muc tieu:
- Hien trinh tu canh, beat do hoa va ket qua dung de nguoi dung duyet/phan hoi.

Frontend can lam:
- Hien moi canh duoi dang card: asset, voice, subtitle, visual beats, overlays, trang thai job va ly do AI chon.
- Preview co play/stop, chuyen canh, xem timestamp overlay va nut "Yeu cau AI sua canh nay".
- Co the hien timeline doc de giai thich nhip dung; khong can ruler/track keo tha/zoom va cong cu edit thu cong day du.
- Trang thai mau goi y:
  - source clip: cam/do
  - AI image/video: xanh/tim
  - stock: xanh la
  - motion graphics: xanh cyan
  - fallback: nau/xam
  - missing/error: do
  - running: vang

Backend can lam:
- Endpoint preview draft neu chua co:
  - Dung asset hien co.
  - Canh thieu visual co the dung fallback neu user confirm.
  - Render nhanh do phan giai thap.
- Endpoint stream preview draft.

Test can lam:
- JS render card voi scene du/missing/error va graphic beat.
- Chon canh de xem ke hoach va gui phan hoi AI.
- Preview draft tu segment co asset.

## Giai doan 5 - Scene inspector va card canh gon hon

Muc tieu:
- Card canh bot dai va ro hanh dong hon.

Frontend can lam:
- Moi card mac dinh hien:
  - preview
  - ten canh/thoi luong/trang thai
  - loi doc
  - audio player/waveform
  - visual prompt ngan
  - nut: Sua, Tao visual, Tao lai voice, Gan file, Preview
- Details nang cao:
  - provider image/video rieng cua canh
  - visual kind/strategy
  - trim/crop
  - overlay/cleanup
  - retry/cancel job
  - source cue
  - risk/detail reason
- Scene inspector ben phai neu can:
  - Khi chon block timeline, hien chi tiet canh dang chon.

Backend can lam:
- Bo sung endpoint update scene fields neu thieu:
  - voice_text
  - visual_prompt
  - duration
  - visual_strategy
  - provider
  - overlays
  - cleanup

Test can lam:
- Test sua scene khong lam mat audio/visual da co.
- Test provider tung canh duoc luu.

## Giai doan 6 - Preflight live va risk meter

Muc tieu:
- Nguoi dung biet truoc canh nao chua render duoc va canh nao con qua phu thuoc nguon.

Backend can lam:
- Preflight tinh:
  - total scenes
  - ready scenes
  - missing visual
  - missing voice
  - missing subtitle
  - missing provider/login/API key
  - source dependency ratio
  - high risk scenes
  - jobs queued/running/error
- Risk logic ban dau:
  - WF Reup ma visual_strategy la source_clip va duration dai => risk cao.
  - Nhieu canh lien tiep dung source_clip => risk cao.
  - Co commentary/overlay/generated/stock/motion la dau vet bien doi de kiem tra; khong tu dong ket luan giam rui ro ban quyen.

Frontend can lam:
- Panel ben phai Storyboard:
  - "San sang render?"
  - "Can tao them gi?"
  - "Muc phu thuoc video goc"
  - nut fix nhanh.

Test can lam:
- Test risk scenes voi source clip dai.
- Test generated/stock/motion lam giam dependency.

## Giai doan 7 - Don giao dien tong cua app

Muc tieu:
- Giam cam giac lang nhang ma khong xoa tinh nang.

Frontend can lam:
- Sidebar chi giu nhom chinh:
  - Tao video
  - Du an
  - Workflow
  - Dieu phoi AI
  - Cai dat
- Moi workspace co 1 hanh dong chinh.
- Panel beta/can cau hinh dua vao details hoac tab phu.
- Trang thai project/job dua vao status panel chung.
- Gan nhan:
  - San sang
  - Beta
  - Can cau hinh
  - Chua nghiem thu

Backend can lam:
- Neu can, them endpoint summary gon:
  - `/api/app/status`
  - project current state
  - blockers
  - next suggested action

Test can lam:
- UI source tests dam bao cac control quan trong van ton tai.
- Test khong mat nut/model/provider quan trong sau khi don UI.

## Giai doan 8 - Chuan hoa workflow chung

Muc tieu:
- Reup, Content, Anh to Video, Bao to Video dung chung flow nhung co cau hinh rieng.

Backend can lam:
- Mo rong `workflows/base.py`:
  - `input_types`
  - `analysis_strategy`
  - `script_mode`
  - `visual_strategy_defaults`
  - `required_steps`
  - `preflight_rules`
  - `manual_actions`
  - `automation_actions`
- Them workflow:
  - `image_to_video`
  - `article_to_video`

Frontend can lam:
- Workflow chon xong thi chi hien input/action phu hop.
- Storyboard dung config workflow de an/hien action.

Test can lam:
- Test moi workflow tra ve config dung.
- Test UI khong hien nham action chinh cua workflow khac.

## Thu tu uu tien de lam that

1. Giai doan 1: schema visual transform plan.
2. Giai doan 2: AI lap ke hoach bien doi visual.
3. Giai doan 3: apply plan tao derived timeline/jobs.
4. Giai doan 4: preview va phan hoi AI trong Storyboard.
5. Giai doan 5: scene inspector/card gon.
6. Giai doan 6: preflight live/risk meter.
7. Giai doan 7: don UI tong.
8. Giai doan 8: them/chuan hoa workflow moi.

## File mockup lien quan

- `_HE_THONG/tai_lieu/ui_mockups/ui-cleanup-01-studio-dashboard.svg`
- `_HE_THONG/tai_lieu/ui_mockups/ui-cleanup-02-storyboard-manual.svg`
- `_HE_THONG/tai_lieu/ui_mockups/ui-cleanup-03-workflow-and-automation.svg`
- `_HE_THONG/tai_lieu/ui_mockups/ui-cleanup-04-storyboard-timeline-preview.svg`
- `_HE_THONG/tai_lieu/ui_mockups/UI_CLEANUP_FEATURE_MAP.md`
- `_HE_THONG/tai_lieu/ui_mockups/STORYBOARD_AND_APP_CLEANUP_SCOPE.md`

## Trang thai trien khai 2026-09-18

- Da bat dau lat cat end-to-end cho overlay text theo canh: AI schema/prompt, normalize preset, luu plan hien co, FFmpeg render tren timeline, kiem thu. Day la nen tang cho cac preset do hoa phuc tap hon, chua phai tinh nang clone day du moi mau trong anh.
- Uu tien tiep: an toan bo cuc theo mat nguoi/subtitle, speech bubble/icon flow/brush label, reviewer kiem tra frame va yeu cau sua, preview trong Storyboard, do lai chi phi/thoi gian render.

## Repo tham khao va cach tich hop

- Chon `https://github.com/browser-use/video-use` lam repo tham khao chinh cho mo hinh AI lap edit decision list -> FFmpeg render -> self-eval. Repo hien co LICENSE MIT (kiem tra 2026-09-18).
- Khong thay the app hien tai hay copy nguyen pipeline cua repo: app da co project DB, workflow, voice, timeline, job va renderer rieng. Chi chon module/ky thuat phu hop sau khi so sanh API, test tren Windows va ghi lai nguon/license neu copy ma.
- Thu tu tich hop: (1) cau truc beat/EDL va self-eval frame o diem cat, (2) sua lai canh loi roi render lai, (3) mo rong preset do hoa. Thanh phan moi trong lat cat nay viet rieng tren renderer hien co; chua nhap ma tu repo ngoai.
- Kiem tra rieng phan OpenMontage AGPL da ton tai trong project truoc khi phat hanh/san pham hoa; khong dua ma cua no vao renderer overlay moi.

## Ke hoach sua rieng phan AI edit - 2026-09-19

Phan nay thay the thu tu uu tien cu cho **lap ke hoach dung va ap dung vao canh**. Muc tieu la AI tu quyet dinh hinh, chu, do hoa, am thanh va nhip dung theo noi dung loi thoai; Storyboard chi la noi xem truoc, phan hoi va duyet. Van lay mot video goc lam nguon chinh cho hai workflow hien tai; nguoi dung co the gan them clip phu.

### Van de duoc xac nhan trong app

- Du an thu 43 co 53 segment nhung edit plan chua duoc ap dung; 53/53 canh khong co transition, effect, overlay. Nhieu canh dai 18-55 giay. Ban render vi vay gan nhu la noi clip goc voi fade va subtitle.
- UI dang co hai luong: "AI dung tung canh" tao edit beats, con "AI len ke hoach tong the va chu dong" tao strategy/overlay. Nguoi dung phai tu hieu va chay ca hai. Apply plan tong the hien moi co the chia lai clip theo thoi luong va lap visual cu; viec nay chua phai ke hoach dung theo noi dung.
- Overlay hien tai chi la chu drawtext voi 4 kind, 3 style, 3 animation; chua the tao hinh/icon, bong hoi, so do va nhan brush nhu anh tham chieu.
- `music_mood` moi la goi y trong plan; render co nhac nen va normalize voice, chua co sound cue rieng cho title/callout/chuyen y va chua co mix/ducking theo loi noi.
- Renderer da co duong ghep canh bang xfade/acrossfade; can dung transition o dung ranh gioi va do thoi gian thuc te, khong fade den o cuoi tung segment.

### Cong cu va vai tro

| Thanh phan | Dung de lam gi | Cach dua vao app |
| --- | --- | --- |
| AI planner hien co | Doc kich ban, transcript, keyframe va phong cach; tao edit decision list co cau truc | Mot lan lap ke hoach toan video, sau do sua theo canh khi can |
| Faster-Whisper + ffprobe/FFmpeg | Lay moc loi noi, do dai voice va phan tich asset; cat/crop/noi canh, mix am thanh, xuat video | Tai su dung pipeline hien co; bo sung moc tu/cum tu cho TTS neu can |
| Remotion/React | Ve va animate title, callout, icon, bong hoi, brush label, so do va bieu do | Tao cac component/preset do hoa rieng, nhan JSON tu cung edit plan; video nguon van la nen |
| FFmpeg audio filters | Mix voice, nhac nen, SFX; fade ngan, duck nhac khi co loi noi, gioi han loudness | Mot audio mix pass co timestamp chinh xac theo scene/beat |
| `video-use` | Tham khao cach mo ta EDL, xem filmstrip va tu kiem tra ket qua tai diem cat | Khong thay the app hay nhap nguyen repo; chi chon ky thuat can thiet |

`motion_composer/` da co Remotion va nhieu component tham khao, nhung la ma OpenMontage AGPL. Tao preset moi trong phan code rieng cua app, khong chen truc tiep vao ma sao chep. Kiem tra giay phep Remotion/OpenMontage neu sau nay phan phoi app hoac van hanh nhu dich vu.

### Mot ban edit plan duy nhat

- `DirectorProfile` cho toan video: loai video (talking head, giai thich, tin tuc...), mau, font ho tro tieng Viet, do dam do hoa, nhip, ty le 16:9/9:16, vung an toan cho mat va subtitle, nhac va bo SFX. AI tham khao video goc va anh phong cach; khong sao chep giao dien Facebook/Messenger trong screenshot.
- `SceneEditPlan` cho tung canh: `segment_id`, thoi luong, y chinh, cau/cum tu lam moc, danh sach `visual_beats`, `graphic_layers`, `audio_cues`, `transition_out`, asset can tao, ly do, trang thai. Moi visual beat co `source_asset_id` hoac `source_video + in/out`, `start/end` tren canh, crop/motion/effect; moi graphic/audio cue co `start/end` tren **cung truc thoi gian**.
- AI chon preset do hoa theo **chuc nang noi dung**: hook -> title; giai thich quy trinh -> so do theo tung buoc; con so -> stat card; hoi/dap -> speech bubble; nhan manh -> brush label. Canh khong can do hoa thi de trong. Moi layer co preset va tham so da kiem duyet, AI khong phat sinh code FFmpeg/React tuy y.
- Luu draft rieng voi timeline dang render. Validate schema, asset, timestamp, ty le khung hinh, do dai chu va xung dot voi mat/subtitle. Sau khi duyet, mot thao tac Apply chuyen **toan bo** plan thanh beat, asset job, graphic layer va sound cue cho renderer; khong doi nguoi dung chay hai luong.
- Khi asset AI/clip phu chua san sang, danh dau `needs_asset` va tao job; neu nguoi dung van render thi dung fallback visual ro rang. Khong chan render chi vi chua co edit plan.

### Trinh tu thuc hien

1. **Dong bo du lieu va timing.** Gan voice/audio thuc te voi canh, tach cum loi quan trong, do do dai thuc. Them `DirectorProfile` va `SceneEditPlan` co version/fingerprint. Migration giu duoc cac project cu.
2. **Hop nhat planner.** Thay hai nut/endpoint nhu hai quy trinh doc lap bang mot luong `Lap ke hoach -> Xem/sua -> Ap dung`. Planner nhin ca nhac dieu toan video va noi dung tung canh, tra ve beat/cue cu the. Bo viec tu chia clip 2-4 beat chi dua tren do dai; khi AI loi, fallback la mot canh nguon co the render duoc, khong gia vo da dung chuyen nghiep.
3. **Tao asset va do hoa.** Tu plan, trich frame, dung clip phu neu co, tao anh AI neu plan can va provider san sang. Lam preset Remotion v1: kinetic title, callout/speech bubble, icon-flow diagram, brush label, stat card. Ho tro vao/giu/ra, bo cuc 9:16/16:9 va tieng Viet co dau. Preview canh va final dung cung component va cung props.
4. **Dung hinh va am thanh.** FFmpeg trim theo source in/out, dung visual beats, transition cut/crossfade co chu dich. Mix voice, nhac nen va SFX co timestamp (whoosh/pop/click/riser chi khi phu hop); ha nhac duoi voice, chong clipping va am thanh bat ngo o diem cat. Remotion xuat lop do hoa cho canh; FFmpeg ghep/mix/xuat final.
5. **Tu kiem tra va sua.** Render ban nhap ngan, xem frame o moc bat/tat do hoa va ranh gioi cat, kiem tra chu de mat/subtitle, canh den, clip lap, nhac lan voice, SFX sai nhịp. Bao loi theo `segment_id`, cho AI de xuat sua plan va render lai canh bi anh huong.
6. **Nghiem thu tren du an that.** Lay 3-5 canh da co voice/video cua du an 43: hook co title + SFX; mot canh giai thich co so do/icon hien lan luot; mot canh co brush label; mot canh khong do hoa. Duyet preview voi nguoi dung, sau do moi nhan rong ca video.

### Tieu chi hoan thanh

- Bam `Lap ke hoach`, duyet, `Ap dung` mot lan; moi canh duoc luu edit plan va renderer doc dung cung ban do. Co the render project cu khong co plan.
- Trong video demo, title/icon/so do/brush xuat hien va bien mat dung cau noi, khong che mat/subtitle; co am thanh diem nhan dong bo voi do hoa, nhac nen khong lan loi doc.
- `Apply` khong duoc bao thanh cong neu visual beat, graphic layer hoac audio cue da duyet khong co trong manifest render. Preview va final phai dung cung preset/thoi diem.
- Test schema/migration, planner -> apply -> manifest -> render cho 16:9 va 9:16; xem lai video that de xac nhan chat luong cam nhan. Khong chi duyet bang unit test hoac so luong effect.
