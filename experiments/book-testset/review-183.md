# Human check of the multi-chunk questions (issue #183)

About 10 minutes. For each question below, read the question, the answer and the evidence sentence of each required chunk, and tick: **(a)** the evidence answers its part of the question; **(b)** the question stands alone (no chunk, page or "the passage" assumed); **(c)** the answer adds nothing from outside the book; **(d)** every listed chunk is needed (removing one leaves part of the question unanswerable). Write any failure next to the id; a question that fails is dropped from the set, and the Recall@k figures are recomputed (`multichunk.py score`).

The first four are flagged by the worker's own review (Claude, the same model that wrote them, so not independent). The next eight are a control sample of unflagged questions drawn with `random.Random(183)` from the 26 unflagged ids (`multichunk.py control data/multi/flags.json`).

## Flagged

### m3  (2 chunks)
- Question: Theo lời tựa, nước ta có sử từ đời nào, lối làm sử của ta theo kiểu nào, và soạn-giả đã làm gì với những chuyện huyền-hoặc khi soạn sách?
- Answer: Có sử từ đời nhà Trần (thế kỷ XIII); theo lối biên niên của Tàu; soạn-giả trích bỏ những sự huyền-hoặc.
- Chunk 0 (copies [0]): "Nước Việt ta khởi đầu có sử từ đời nhà Trần, vào quãng thế-kỷ thứ XIII. Từ đó trở đi nhà nào lên làm vua cũng trọng sự làm sử. Nhưng cái lối làm sử của ta theo lối biên niên của Tàu"
- Chunk 8 (copies [8]): "rồi đem trích bỏ những sự huyền-hoặc đi mà soạn ra bộ sách này"
- Why flagged: The first part repeats the single-chunk question c0-seen; the "huyền-hoặc" part comes from a chunk that only states the aim of the book.
- [ ] a  [ ] b  [ ] c  [ ] d

### m21  (2 chunks)
- Question: Khi cho quân Minh về nước, Bình-định-vương cấp cho thủy-quân bao nhiêu chiếc thuyền, và theo bài Bình Ngô đại-cáo thì ở đâu máu chảy thành sông, ở đâu xác đầy ngoài nội?
- Answer: 500 chiếc thuyền; dưới Ninh-kiều máu chảy thành sông, bến Tụy-động xác đầy ngoài nội.
- Chunk 307 (copies [307]): "Vương không giết người Minh lại cấp cho thủy-quân 500 chiếc thuyền giao cho Phương Chính và Mã Kỳ quản-lĩnh"
- Chunk 310 (copies [310]): "Dưới Ninh-kiều máu chảy thành sông; bến Tụy-động xác đầy ngoài nội."
- Why flagged: Chunk 310 is a verse translation of the Bình Ngô đại-cáo; check that its line answers the question without the rest of the poem.
- [ ] a  [ ] b  [ ] c  [ ] d

### m2  (3 chunks)
- Question: Khổng-tử sinh vào năm nào trước Tây-lịch, vua nhà Hán nào sai người sang Thiên-trúc lấy kinh Phật, và theo tác giả vì đâu mà người mình tiến hóa chậm?
- Answer: Năm 551 tr. Tây-lịch; vua Minh-đế nhà Đông-Hán; vì sùng-mộ văn-minh Tàu, chỉ bắt chước mà không tìm cách phát-minh.
- Chunk 88 (copies [88]): "sinh ở nước Lỗ (thuộc tỉnh Sơn-đông) vào năm 551 trước Tây-lịch"
- Chunk 94 (copies [94]): "Đến đời vua Minh-đế nhà Đông-Hán, có Ban Siêu đi sứ các nước ở Tây-vực biết đạo Phật thịnh-hành ở phương Tây. Vua bèn sai Thái Am đi sang Thiên-trúc lấy được 42 chương kinh"
- Chunk 98 (copies [98]): "Cách mình sùng-mộ văn-minh của Tàu như thế, cho nên không chịu so-sánh cái hơn cái kém, không tìm cách phát-minh những điều hay tốt ra, chỉ đinh-ninh rằng người ta hơn mình, mình chỉ bắt chước người ta là đủ."
- Why flagged: Three unrelated facts (Confucius, Buddhism, why the Vietnamese were slow); check that the evidence for "which Han emperor" really names Minh-đế.
- [ ] a  [ ] b  [ ] c  [ ] d

### m24  (2 chunks)
- Question: Vua Thánh-tông nhà Lý đổi quốc-hiệu là gì, và vua Nhân-tông lên làm vua lúc mấy tuổi, ai làm quan Phụ-chính?
- Answer: Đổi quốc-hiệu là Đại-Việt; Nhân-tông lên làm vua lúc 7 tuổi, Thái-sư Lý đạo Thành làm phụ-chính.
- Chunk 122 (copies [122]): "tức là vua Thánh-tông , ngài đổi quốc-hiệu là Đại-Việt ."
- Chunk 125 (copies [125]): "Lúc Nhân-tông lên làm vua mới có 7 tuổi, có quan Thái-sư là Lý đạo Thành làm phụ-chính."
- Why flagged: Two facts only; check that Nhân-tông being 7 and Lý Đạo Thành being regent is in the evidence as written.
- [ ] a  [ ] b  [ ] c  [ ] d

## Control

### m12  (4 chunks)
- Question: Tác giả cho người An-nam hay có tính gì nên mới rước người Tàu sang; nhà Minh đặt ba ti nào để cai-trị nước ta; Giản-định-đế bị Trương Phụ bắt rồi giải về đâu; và Trần quí Khoách tự-tử bằng cách nào khi bị giải về Yên-kinh?
- Answer: Tính ỷ-lại, chỉ muốn nhờ người; Bố-chính-ti, Án-sát-ti, Chưởng-đô-ti; giải về Kim-lăng; nhảy xuống bể tự-tử.
- Chunk 257 (copies [257]): "Lại nhân vì người An-nam ta hay có tính ỷ-lại, có việc gì thì chỉ muốn nhờ người, chứ tự mình không biết kiên-nhẫn"
- Chunk 259 (copies [259]): "Lại đặt ra ba ti là: Bố-chính-ti, Án-sát-ti, Chưởng-đô-ti, và cả thảy ở trong nước lập ra 472 nha-môn để cai-trị"
- Chunk 263 (copies [263]): "gặp quân Trương Phụ đuổi đến bắt được giải về Kim-lăng."
- Chunk 266 (copies [266]): "Đi đến giữa đường, Quí Khoách nhảy xuống bể tự-tử"
- [ ] a  [ ] b  [ ] c  [ ] d

### m11  (3 chunks)
- Question: Hưng-đạo-vương xin về trí-sĩ ở đâu; vua Hiến-tông lên ngôi lúc mấy tuổi và quyền chính ở tay ai; và trong trận đánh Ai-lao ở ấp Nam-nhung ai chết đuối?
- Answer: Ở Vạn-kiếp; 10 tuổi, quyền chính ở tay Minh-tông Thượng-hoàng; Đoàn nhữ Hài.
- Chunk 208 (copies [208]): "Hưng-đạo-vương làm quan đến đời vua Anh-tông thì xin về trí-sĩ ở Vạn-kiếp."
- Chunk 215 (copies [215]): "Thái-tử Vượng mới có 10 tuổi, lên làm vua, tức là vua Hiến-tông . Hiến-tông chỉ làm vua lấy vì mà thôi, quyền chính ở cả tay Minh-tông Thượng-hoàng"
- Chunk 217 (copies [217]): "quan quân thua chạy cả xuống sông, chết đuối nhiều lắm. Đoàn nhữ Hài cũng chết đuối."
- [ ] a  [ ] b  [ ] c  [ ] d

### m7  (2 chunks)
- Question: Dưới đời Lý Thần-tông, quân lính được đổi phiên cứ bao lâu một lần để về làm ruộng, và dưới đời Lý Anh-tông vua Tàu đổi phong vua ta từ Giao-chỉ quận-vương thành gì?
- Answer: Cứ 6 tháng đổi phiên một lần; đổi thành An-nam quốc-vương.
- Chunk 135 (copies [135]): "Quân lính thì cho đổi phiên, cứ lần lượt 6 tháng một, được về làm ruộng."
- Chunk 138 (copies [138]): "Nhưng Tàu vẫn phong cho vua ta là Giao-chỉ quận-vương, đến bấy giờ mới đổi là An-nam quốc-vương."
- [ ] a  [ ] b  [ ] c  [ ] d

### m1  (3 chunks)
- Question: Sau khi thua trận ở nước Nam, nhà Nguyên định đi đường nào sang báo thù, tướng Ô Mã Nhi cuối cùng chết ra sao, và vì sao nhà Nguyên bãi việc binh?
- Answer: Định đi đường châu Khâm, châu Liêm; Ô Mã Nhi bị đánh đắm thuyền cho chết đuối theo mưu Hưng-đạo-vương; bãi binh vì Nguyên Thế-tổ Hốt-tất-Liệt mất.
- Chunk 190 (copies [190]): "định đến tháng tám thì cất quân noi đường châu Khâm, châu Liêm sang đánh nước Nam để báo thù."
- Chunk 201 (copies [201]): "bèn dùng mưu của Hưng-đạo-vương sai người đưa đi đến giữa bể, đánh đắm thuyền, cho chết đuối"
- Chunk 204 (copies [204]): "thì Nguyên Thế-tổ là Hốt-tất-Liệt mất, Nguyên Thánh-tông lên ngôi, mới bãi việc binh"
- [ ] a  [ ] b  [ ] c  [ ] d

### m22  (3 chunks)
- Question: Theo lời tựa, người mình xưa học sử nước nào mà không học sử nước nhà; nhà Lê thịnh-trị rực-rỡ nhất vào những năm niên-hiệu nào; và soạn-giả ví bộ sử lược này với thứ áo gì?
- Answer: Học sử Tàu; những năm Quang-thuận (1460-1469) và Hồng-đức (1470-1497); áo vải (ví với chưa có áo lụa thì mặc tạm áo vải).
- Chunk 2 (copies [1, 2]): "hễ ai cắp quyển sách đi học thì chỉ học sử Tàu,chứ không học sử nước nhà."
- Chunk 6 (copies [6]): "nhất là về những năm Quang-thuận (1460-1469) và Hồng-đức (1470-1497), thì sự văn-trị và võ-công đã là rực-rỡ lắm."
- Chunk 9 (copies [9]): "Bây giờ ta chưa có áo lụa, ta hãy mặc tạm áo vải, tuy nó xấu-xí nhưng nó có thể làm cho ta đỡ rét."
- [ ] a  [ ] b  [ ] c  [ ] d

### m19  (3 chunks)
- Question: Nguyên-chủ lập ai làm An-nam quốc-vương; khi vua Nhân-tông muốn hàng giặc để cứu muôn dân, Hưng-đạo-vương tâu thế nào; và trong bài hịch Hưng-đạo-vương khuyên tướng-sĩ làm gì?
- Answer: Lập Trần di Ái; tâu xin chém đầu mình trước rồi hãy hàng; khuyên dạy-bảo quân-sĩ, luyện-tập cung tên.
- Chunk 168 (copies [168]): "bèn lập Trần di Ái làm An-nam quốc-vương"
- Chunk 172 (copies [172]): "Nếu bệ-hạ muốn hàng, xin trước hãy chém đầu tôi đi đã, rồi sau sẽ hàng!"
- Chunk 176 (copies [176]): "nên cẩn-thận như nơi củi lửa, nên giữ-gìn như kẻ húp canh, dạy-bảo quân-sĩ, luyện-tập cung tên"
- [ ] a  [ ] b  [ ] c  [ ] d

### m16  (4 chunks)
- Question: Ở trận Khả-lưu Bình-định-vương dùng cách nghi-binh nào vào ban đêm; quân của ông tiến ra Đông-đô giữ kỷ-luật ra sao; người tên Hồ Ông được lập làm vua thì đổi tên là gì; và Liễu Thăng đem bao nhiêu quân, ngựa sang đánh?
- Answer: Ban đêm đốt lửa; giữ kỷ-luật rất nghiêm, không xâm-phạm của ai; đổi tên là Trần Cao; 10 vạn quân, hai vạn ngựa.
- Chunk 285 (copies [285]): "ban ngày thì kéo cờ đánh trống, ban đêm thì bắt đốt lửa để làm nghi binh"
- Chunk 288 (copies [288]): "Quân của Bình-định-vương đi đến đâu giữ kỷ-luật rất nghiêm, không xâm-phạm đến của ai chút gì"
- Chunk 295 (copies [295]): "bèn cho người đi đón Hồ Ông về đổi tên là Trần Cao lập nên làm vua"
- Chunk 299 (copies [299]): "đem 10 vạn quân, hai vạn ngựa, đi đường Quảng-tây sang đánh cửa Ba-lụy"
- [ ] a  [ ] b  [ ] c  [ ] d

### m8  (4 chunks)
- Question: Vua Thái-tổ nhà Lê đặt quốc-hiệu là gì; vua Thánh-tông lúc đầu chia nước ra làm mấy đạo; Thánh-tông dặn triều-thần phải giữ-gìn điều gì; và dưới đời Chiêu-tông vì sao Mạc đăng Dung không đánh Nguyễn hoằng Dụ?
- Answer: Đại-Việt; 12 đạo; đừng để ai lấy mất một phân núi, một tấc sông vua Thái-tổ để lại; vì Đăng Dung nhận được thư riêng của Hoằng Dụ.
- Chunk 314 (copies [314]): "Bình-định-vương lên ngôi tức là vua Thái-tổ nhà Lê , đặt quốc-hiệu là Đại-Việt ."
- Chunk 327 (copies [327]): "Thánh-tông chia nước ra làm 12 đạo là Thanh-hóa, Nghệ-an, Thuận-hóa, Thiên-trường, Nam-sách, Quốc-oai, Bắc-giang, An-bang, Hưng-hóa, Tuyên-quang, Thái-nguyên, Lạng-sơn."
- Chunk 338 (copies [338]): "Ta phải giữ-gìn cho cẩn-thận, đừng để cho ai lấy mất một phân núi, một tấc sông của vua Thái-tổ để lại."
- Chunk 346 (copies [346, 347]): "Nhưng Đăng Dung tiếp được thư của Hoằng Dụ viết riêng cho mình, bèn không đánh, đem quân trở về."
- [ ] a  [ ] b  [ ] c  [ ] d
