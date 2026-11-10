# Review of the book test set (issue #178)

**What this is.** An **LLM review (Claude)** of `questions.jsonl`, done 2026-11-10 by chat d48465 reading each pair against its evidence sentence, and against the source chunk where the evidence alone did not settle it. No API calls. **It is not a human check.** The human check is recorded separately, under "Human check" below, once you have filled it in.

**Scope.** 215 seen/blind pairs (430 questions). The 25 unanswerable questions were not reviewed here: they have no evidence to check against.

**Criteria.** (a) the evidence answers the question; (b) the question stands alone (says who, what or when, and does not depend on the chapter); (c) the answer adds no fact that is not in the book; (d) the blind rewrite keeps the meaning and the kind of answer asked for.

**Result.** 24 pairs flagged (23 on a criterion, 1 as a near-duplicate); 191 pass. Proposed: 5 drops; the rest are fixes or your call. A fix to the seen question or the answer applies to both versions of the pair.

Counts by criterion: a: 3, b: 11, c: 1, d: 8, dup: 1.

**How to answer.** For each entry, write on its "Your verdict" line `ok` (my flag is wrong; keep the pair as it is), `fix` (apply my fix, or write your own), or `drop`. Write `bad` on a control entry that should have been flagged. Anything left blank I take as agreement with my verdict.

One note outside the criteria: c216 (Ai Lao) takes "năm giáp-tuất (1384)" from the book. Giáp-tuất is 1334, and Minh Tông died in 1357, so 1384 looks like a misprint in the book itself. The pair is faithful to the book, so it is not flagged.

## Flagged pairs

### c6-seen  (Quyển I > Tựa)

- **Question (seen):** Vì sao nhà Lý và nhà Trần có công gây nên quốc hồn mạnh mẽ?
- **Rewrite (blind):** Tại sao nhà Lý và nhà Trần lại tạo được tinh thần dân tộc mạnh mẽ?
- **Answer:** Vì khi họ Hồ quấy rối, người Tàu toan kiêm tính, người mình biết đồng tâm hiệp lực khôi phục giang sơn.
- **Evidence:** Nhà Lý và nhà Trần lại có công gây nên cái quốc-hồn mạnh-mẽ, khiến cho về sau đến đời Trần mạt, nhân khi họ Hồ quấy-rối, người Tàu đã toan đường kiêm-tính, người mình biết đồng tâm hiệp lực mà khôi-phục lại giang-sơn nhà.
- **LLM verdict (Claude):** **flag, (a) evidence answers the question.** The evidence says what the Lý and Trần built (a national spirit) and its later effect; it gives no cause, so the answer to "vì sao" is the consequence, not the reason. Proposed: fix: ask "Nhờ quốc hồn do nhà Lý, nhà Trần gây nên, người Việt đã làm được gì khi người Tàu toan kiêm tính cuối đời Trần?", same answer.
- **Human verdict (user):** drop

### c16-seen  (Quyển I > Nước Việt Nam)

- **Question (seen):** Sách Việt Nam sử được chia thành mấy phần?
- **Rewrite (blind):** Sách Lịch sử Việt Nam gồm bao nhiêu phần?
- **Answer:** 5 phần
- **Evidence:** Nay ta nên theo từng thời-đại mà chia sách Việt-nam sử ra 5 phần để cho tiện sự kê-cứu
- **LLM verdict (Claude):** **flag, (d) rewrite keeps meaning and answer type.** The rewrite turns "Việt Nam sử" (this book) into "Lịch sử Việt Nam", any history book, so it no longer points at one answer; it also nearly repeats c3 (5 thời đại). Proposed: drop.
- **Human verdict (user):** drop

### c36-seen  (Quyển I > Phần I > Chương III: Xã hội nước Tàu)

- **Question (seen):** Triệu Đà đã làm gì khi lập ra nước Nam Việt?
- **Rewrite (blind):** Triệu Đà thành lập nước Nam Việt bằng cách nào?
- **Answer:** Đem văn minh nước Tàu sang truyền bá ở phương nam.
- **Evidence:** Triệu Đà lập ra nước Nam-việt, đem văn-minh nước Tàu sang truyền-bá ở phương nam
- **LLM verdict (Claude):** **flag, (d) rewrite keeps meaning and answer type.** The seen question asks what Triệu Đà did after founding Nam Việt; the rewrite asks how he founded it, which the evidence does not answer. Proposed: fix rewrite: "Sau khi lập nước Nam Việt, Triệu Đà đã làm gì?".
- **Human verdict (user):** fix

### c44-seen  (Quyển I > Phần I > Chương IV: Nhà Triệu)

- **Question (seen):** Nước Nam bị nhà Hán chiếm lấy vào năm nào theo Tây lịch?
- **Rewrite (blind):** Việt Nam bị Trung Quốc đô hộ vào thời gian nào?
- **Answer:** Năm 111 trước Tây lịch
- **Evidence:** Năm ấy là năm canh-ngọ (111 tr. Tây-lịch), nước Nam bị người Tàu chiếm lấy, cải là Giao-chỉ-bộ , chia ra làm 9 quận, và đặt quan cai-trị như các châu quận bên Tàu vậy.
- **LLM verdict (Claude):** **flag, (d) rewrite keeps meaning and answer type.** The rewrite drops "nhà Hán" and asks when Việt Nam was put under Chinese rule, which has several answers (three Bắc thuộc periods, the Minh). Proposed: fix rewrite: "Nhà Hán chiếm nước Nam vào năm nào?".
- **Human verdict (user):** fix

### c45-seen  (Quyển I > Phần II > Chương I: Bắc Thuộc lần thứ nhất)

- **Question (seen):** Theo chương này, vào năm 111 trước Tây lịch, vua Vũ đế nhà Hán sai hai tướng nào sang đánh nhà Triệu?
- **Rewrite (blind):** Năm 111 trước công nguyên, vua Hán Vũ Đế phái hai tướng nào đi đánh nước Triệu?
- **Answer:** Lộ Bác Đức và Dương Bộc.
- **Evidence:** Năm canh-ngọ (111 tr. Tây-lịch) vua Vũ-đế nhà Hán sai Lộ bác Đức và Dương Bộc sang đánh nhà Triệu , lấy nước Nam-việt, rồi cải là Giao-chỉ-bộ , và chia ra làm 9 quận, là những quận này:
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Theo chương này" depends on the chapter. Proposed: fix: delete "Theo chương này,"; the year and names already fix the event.
- **Human verdict (user):** fix

### c48-seen  (Quyển I > Phần II > Chương II: Trưng Vương)

- **Question (seen):** Ai là vợ của Thi Sách, người đã cùng em gái nổi lên khởi binh đánh Tô Định?
- **Rewrite (blind):** Bà Trưng Trắc là vợ của ai? Bà cùng em gái đánh Tô Định.
- **Answer:** Trưng Trắc
- **Evidence:** Vợ Thi Sách là Trưng Trắc con gái quan lạc-tướng ở huyện Mê-linh (làng Hạ-lôi, huyện Yên-lãng, tỉnh Phúc-yên) cùng với em gái là Trưng Nhị nổi lên đem quân về đánh Tô Định.
- **LLM verdict (Claude):** **flag, (d) rewrite keeps meaning and answer type.** The rewrite asks whose wife Trưng Trắc was, so its answer is Thi Sách, not Trưng Trắc. Proposed: fix rewrite: "Vợ của Thi Sách, người cùng em gái đánh Tô Định, là ai?".
- **Human verdict (user):** fix

### c89-seen  (Quyển I > Phần II > Chương VI: Kết quả của thời đại Bắc Thuộc)

- **Question (seen):** Khổng Tử dạy mọi người điều gì?
- **Rewrite (blind):** Khổng Tử dạy điều gì về cách sống?
- **Answer:** Điều gì mà mình không muốn người ta làm cho mình, thì mình đừng làm cho ai.
- **Evidence:** Đối với mọi người thì ngài dạy: « Kỷ sở bất dục, vật thi ư nhân : điều gì mà mình không muốn người ta làm cho mình, thì mình đừng làm cho ai ».
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Khổng Tử dạy mọi người điều gì?" has many correct answers; the gold one is a single maxim. Proposed: fix: "Khổng Tử dạy điều gì về cách đối xử với người khác, điều mình không muốn thì sao?" or drop.
- **Human verdict (user):** fix: seen "Khổng Tử dạy cách đối xử với người khác thế nào?"; blind "Theo Khổng Tử, nên cư xử với người khác ra sao?"

### c142-seen  (Quyển I > Phần III > Chương V: Nhà Lý (tiếp theo))

- **Question (seen):** Ai là người cậu của Trần Thị được phong làm Thái úy Thuận lưu bá?
- **Rewrite (blind):** Chú của Trần Thị, người được phong Thái úy Thuận lưu bá, là ai?
- **Answer:** Tô Trung Từ
- **Evidence:** Huệ-tông bèn phong cho Tự Khánh làm Chương-tín-hầu và cho người cậu Trần-thị là Tô trung Từ làm Thái-úy Thuận-lưu-bá.
- **LLM verdict (Claude):** **flag, (d) rewrite keeps meaning and answer type.** The seen question says "người cậu" (mother's brother); the rewrite says "Chú" (father's brother), a different relation. Proposed: fix rewrite: "Cậu của Trần thị, người được phong Thái úy Thuận lưu bá, là ai?".
- **Human verdict (user):** fix

### c144-seen  (Quyển I > Phần III > Chương V: Nhà Lý (tiếp theo))

- **Question (seen):** Vua Lý Huệ Tông truyền ngôi cho ai vào tháng 10 năm 1224?
- **Rewrite (blind):** Ai được vua Lý Huệ Tông nhường ngôi vào cuối năm 1224?
- **Answer:** Chiêu Thánh công chúa (Lý Chiêu Hoàng)
- **Evidence:** Tháng 10 năm giáp-thân (1224) Huệ-tông truyền ngôi cho Chiêu-thánh công-chúa
- **LLM verdict (Claude):** **flag, (b) question stands alone.** Duplicate of c143: same question, same answer, overlapping chunks. Keeping both double-counts one fact. Proposed: drop (keep c143).
- **Human verdict (user):** drop

### c158-seen  (Quyển I > Phần III > Chương VI: Nhà Trần (Thời kỳ thứ nhất))

- **Question (seen):** Khi quân Mông Cổ vào thành Thăng Long, họ đã làm gì?
- **Rewrite (blind):** Quân Mông Cổ đã làm gì khi vào thành Thăng Long?
- **Answer:** Quân Mông Cổ giết phá cả nam phụ lão ấu trong thành.
- **Evidence:** Quân Mông-cổ vào thành Thăng-long, thấy ba người sứ Mông-cổ còn phải trói, giam ở trong ngục, đến khi cởi trói ra thì một người chết. Ngột-lương-hợp-thai thấy thế tức giận quá, cho quân ra giết phá cả nam phụ lão ấu ở trong thành.
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Khi quân Mông Cổ vào thành Thăng Long" does not say which time; they entered in 1258, 1285 and 1287-88. Proposed: fix: "Dưới thời Trần Thái Tông, khi quân Mông Cổ vào thành Thăng Long, họ đã làm gì?" (chunk 158 is the first invasion, under Thái Tông).
- **Human verdict (user):** fix

### c167-seen  (Quyển I > Phần III > Chương VII: Giặc nhà Nguyên - I)

- **Question (seen):** Ai được vua Nhân Tông sai sang thay cho mình để đáp ứng yêu cầu của Nguyên chủ năm 1282?
- **Rewrite (blind):** Năm 1282 Nguyên chủ yêu cầu gì mà vua Nhân Tông cử người sang thay mình?
- **Answer:** Trần Di Ái, Lê Tuân, Lê Mục
- **Evidence:** Nhân-tông sai người chú họ là Trần di Ái và Lê Tuân , Lê Mục sang thay cho mình.
- **LLM verdict (Claude):** **flag, (d) rewrite keeps meaning and answer type.** The seen question asks who was sent; the rewrite asks what Nguyên demanded, a different question with a different answer. Proposed: fix rewrite: "Năm 1282 vua Trần Nhân Tông cử ai sang thay mình theo đòi hỏi của nhà Nguyên?".
- **Human verdict (user):** fix

### c177-seen  (Quyển I > Phần III > Chương VII: Giặc nhà Nguyên - I)

- **Question (seen):** Trần Hưng Đạo soạn sách gì để dạy các tướng sĩ?
- **Rewrite (blind):** Trần Hưng Đạo đã viết sách gì để chỉ dạy các binh sĩ?
- **Answer:** Binh thư yếu lược
- **Evidence:** Nay ta soạn hết các binh-pháp của các nhà danh-gia hợp lại làm một quyển gọi là « Binh-thư yếu-lược ».
- **LLM verdict (Claude):** **flag, near-duplicate (not a criterion).** Same answer (Binh thư yếu lược) as c173, asked from the Hịch text instead of the narrative. Not a criterion failure; flagged as a near-duplicate. Proposed: keep or drop: your call.
- **Human verdict (user):** drop

### c185-seen  (Quyển I > Phần III > Chương VII: Giặc nhà Nguyên - I)

- **Question (seen):** Theo Việt Nam sử lược, trong trận Tây Kết, tướng nhà Trần nào đã chém được Toa Đô?
- **Rewrite (blind):** Trong trận Tây Kết theo Việt Nam sử lược, ai là tướng nhà Trần đã giết Toa Đô?
- **Answer:** Tướng nhà Trần chém được Toa Đô (nhưng không nêu tên cụ thể trong đoạn này).
- **Evidence:** TRẬN TÂY-KẾT: Tướng nhà Trần chém được Toa Đô.
- **LLM verdict (Claude):** **flag, (a) evidence answers the question.** The evidence names no general, and the answer says so ("không nêu tên"). The question has no answer in the book. Proposed: drop.
- **Human verdict (user):** drop

### c202-seen  (Quyển I > Phần III > Chương VIII: Giặc nhà Nguyên - II)

- **Question (seen):** Ai đã sai đem đốt cả tráp biểu hàng của các quan để cho yên lòng mọi người?
- **Rewrite (blind):** Ai đã ra lệnh đốt hết tập biểu xin hàng của các quan để trấn an mọi người?
- **Answer:** Thượng hoàng
- **Evidence:** Đình-thần muốn lục ra để trị tội, nhưng Thượng-hoàng nghĩ rằng làm tội những đồ tiểu-nhân cũng vô ích, bèn sai đem đốt cả tráp đi, cho yên lòng mọi người.
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Thượng hoàng" is a title held by many; the answer does not say which one (Trần Thánh Tông, after the 1288 war). Proposed: fix: answer "Thượng hoàng (Trần Thánh Tông)"; question "Năm 1289, khi xét tội những người hàng giặc Nguyên, ai đã sai đốt cả tráp biểu hàng?" The book says elsewhere that Thánh Tông gave the throne to Nhân Tông, so the name is in the book though not in this chunk..
- **Human verdict (user):** fix

### c203-seen  (Quyển I > Phần III > Chương VIII: Giặc nhà Nguyên - II)

- **Question (seen):** Sau khi thưởng công phạt tội xong, Thượng hoàng nhà Trần về đâu và mất khi nào?
- **Rewrite (blind):** Sau khi thưởng phạt xong, Thượng hoàng thời Trần về đâu và mất lúc nào?
- **Answer:** Thượng hoàng về phủ Thiên Trường và mất vào tháng năm năm Canh Dần (1290).
- **Evidence:** Thưởng công, phạt tội xong rồi, Thượng-hoàng về phủ Thiên-trường, đến tháng năm, năm canh-dần (1290) thì mất.
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Thượng hoàng nhà Trần" does not name which one (Trần Thánh Tông, died 1290). Proposed: fix: "Thượng hoàng (Trần Thánh Tông)" in the answer; name him in the question.
- **Human verdict (user):** fix

### c229-seen  (Quyển I > Phần III > Chương X: Nhà Trần (Thời kỳ thứ ba))

- **Question (seen):** Trong thời kỳ thứ ba của nhà Trần, quân Chiêm Thành đã vào phá kinh thành bao nhiêu lần?
- **Rewrite (blind):** Quân Chiêm Thành tấn công kinh thành bao nhiêu lần vào thời kỳ thứ ba nhà Trần?
- **Answer:** Ba lần
- **Evidence:** Quân Chiêm-thành bấy giờ ra vào nước Nam ta như đi vào chỗ không người, cho nên trong mấy năm mà vào phá kinh-thành ba lần; ba lần Thượng-hoàng cùng Đế Hiễn phải bỏ thành mà chạy.
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Thời kỳ thứ ba của nhà Trần" is this book's chapter split, not a common term. Proposed: fix: "Dưới thời Đế Hiện (Trần Phế Đế), quân Chiêm Thành vào phá kinh thành bao nhiêu lần?" (the chunk names Thượng hoàng and Đế Hiễn).
- **Human verdict (user):** fix

### c230-seen  (Quyển I > Phần III > Chương X: Nhà Trần (Thời kỳ thứ ba))

- **Question (seen):** Thuế thân ở Việt Nam bắt đầu từ khi nào và do ai đề xuất?
- **Rewrite (blind):** Thuế thân ra đời lúc nào và ai là người đưa ra ý tưởng đó?
- **Answer:** Thuế thân bắt đầu từ thời vua Nghệ Tông, do Đỗ Tử Bình đề xuất.
- **Evidence:** Đỗ tử Bình xin với vua bắt mỗi suất đinh mỗi năm phải đóng 3 quan tiền thuế. Thuế thân sinh ra từ đấy.
- **LLM verdict (Claude):** **flag, (c) answer adds no outside fact.** The answer says "thời vua Nghệ Tông"; the chunk says only "xin với vua" and gives no date, so the reign is added. Proposed: fix answer: "Từ khi Đỗ Tử Bình xin bắt mỗi suất đinh đóng 3 quan tiền mỗi năm (cuối đời Trần)"; or ask only who proposed it.
- **Human verdict (user):** fix: ask only who. seen "Ai đã xin vua đặt ra thuế thân, bắt mỗi suất đinh đóng 3 quan tiền mỗi năm, cuối đời Trần?"; answer "Đỗ Tử Bình"

### c298-seen  (Quyển I > Phần III > Chương XIV: Mười năm đánh quân Tàu)

- **Question (seen):** Vương đặt ra bao nhiêu điều kỷ luật cho các tướng sĩ?
- **Rewrite (blind):** Vua ban hành bao nhiêu quy tắc cho quân lính?
- **Answer:** 10 điều
- **Evidence:** Vương lại đặt ra 10 điều để làm kỷ-luật cho các tướng-sĩ:
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Vương" is unnamed in both versions (Bình Định Vương Lê Lợi). Proposed: fix: "Bình Định Vương Lê Lợi đặt ra bao nhiêu điều kỷ luật cho tướng sĩ?" and the same in the rewrite.
- **Human verdict (user):** fix

### c304-seen  (Quyển I > Phần III > Chương XIV: Mười năm đánh quân Tàu)

- **Question (seen):** Vương sai những ai sang sứ nhà Minh để đem tờ biểu và phương vật?
- **Rewrite (blind):** Ai được vua cử đi sứ nhà Minh mang biểu và đồ cống?
- **Answer:** Lê Thiếu Dĩnh, Lê Quang Cảnh và Lê Đức Huy
- **Evidence:** Vương sai Lê thiếu Dĩnh , Lê quang Cảnh và Lê đức Huy đem tờ biểu và phương-vật sang sứ nhà Minh.
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Vương" is unnamed (Bình Định Vương Lê Lợi), and the rewrite says "vua". Proposed: fix: name Bình Định Vương Lê Lợi in both.
- **Human verdict (user):** fix

### c305-seen  (Quyển I > Phần III > Chương XIV: Mười năm đánh quân Tàu)

- **Question (seen):** Trương Phụ xin đặt vùng đất Việt bấy giờ làm gì?
- **Rewrite (blind):** Trương Phụ đã xin đặt tên cho vùng đất Việt thời đó là gì?
- **Answer:** Quận huyện
- **Evidence:** Bấy giờ quan tổng-binh Trương Phụ tìm chưa được khắp, đã xin đặt làm quận huyện.
- **LLM verdict (Claude):** **flag, (d) rewrite keeps meaning and answer type.** The seen question asks what status Trương Phụ proposed (quận huyện); the rewrite asks what name he proposed. Proposed: fix rewrite: "Trương Phụ xin biến đất Việt thành gì?".
- **Human verdict (user):** fix

### c307-seen  (Quyển I > Phần III > Chương XIV: Mười năm đánh quân Tàu)

- **Question (seen):** Ai là người được Bình Định vương giao cho việc soạn thảo tờ Bình Ngô đại cáo?
- **Rewrite (blind):** Nguyễn Trãi viết Bình Ngô đại cáo theo lệnh của ai?
- **Answer:** Ông Nguyễn Trãi
- **Evidence:** Bình-định-vương dẹp xong giặc Minh rồi, sai ông Nguyễn Trãi làm tờ bá cáo cho thiên-hạ biết.
- **LLM verdict (Claude):** **flag, (d) rewrite keeps meaning and answer type.** The rewrite reverses the question: it asks who ordered Nguyễn Trãi, so its answer is Bình Định Vương. Proposed: fix rewrite: "Ai được Bình Định Vương sai viết Bình Ngô đại cáo?".
- **Human verdict (user):** fix

### c308-seen  (Quyển I > Phần III > Chương XIV: Mười năm đánh quân Tàu)

- **Question (seen):** Theo lời Trần Trọng Kim, hai vị tướng nào của quân Nguyên bị quân nhà Trần giết và bắt sống?
- **Rewrite (blind):** Hai tướng Nguyên nào bị quân Trần giết và bắt sống?
- **Answer:** Toa Đô bị giết ở cửa Hàm Tử, Ô Mã bị bắt sống ở sông Bạch Đằng.
- **Evidence:** Cửa Hàm-tử giết tươi Toa Đô, sông Bạch-đằng bắt sống Ô Mã.
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Theo lời Trần Trọng Kim": the line is from the Bình Ngô đại cáo (Nguyễn Trãi), which the book quotes; the attribution is wrong. Proposed: fix: "Theo Bình Ngô đại cáo, ...".
- **Human verdict (user):** fix

### c310-seen  (Quyển I > Phần III > Chương XIV: Mười năm đánh quân Tàu)

- **Question (seen):** Trong trận Bồ Đằng, quân khởi nghĩa đã đánh tan quân Minh như thế nào?
- **Rewrite (blind):** Quân khởi nghĩa đã đánh bại quân Minh trong trận Bồ Đằng ra sao?
- **Answer:** Trận Bồ Đằng sấm vang sét dậy
- **Evidence:** Trận Bồ-đằng sấm vang sét dậy, miền Trà-lân trúc phá tro bay.
- **LLM verdict (Claude):** **flag, (a) evidence answers the question.** The answer is a figure of speech ("sấm vang sét dậy"), not a fact about how the battle was won. Proposed: drop.
- **Human verdict (user):** drop

### c331-seen  (Quyển I > Phần III > Chương XV: Nhà Lê)

- **Question (seen):** Theo quy định trong Việt Nam sử lược, các phủ huyện phải lập bia ở đâu để cấm con trai con gái cùng tắm một bến?
- **Rewrite (blind):** Thời xưa, chính quyền yêu cầu các phủ huyện dựng bia ở chỗ nào để ngăn nam nữ tắm chung một bến?
- **Answer:** Ở các nơi sở tại
- **Evidence:** 18. Phủ huyện phải lập bia ở các nơi sở-tại để cấm con-trai con-gái không được cùng tắm một bến, để cho có phân biệt.
- **LLM verdict (Claude):** **flag, (b) question stands alone.** "Theo quy định trong Việt Nam sử lược" gives no ruler or era, and the rewrite says only "thời xưa"; the same evidence also yields c332. Proposed: drop (keep c332).
- **Human verdict (user):** drop


## Control sample: 10 unflagged pairs (seed 178)

Drawn with `random.Random(178).sample(sorted(unflagged_ids), 10)`. Each passed all four criteria in the LLM review. They are here so your check also measures what the LLM review missed.

### c143-seen  (Quyển I > Phần III > Chương V: Nhà Lý (tiếp theo))

- **Question (seen):** Huệ Tông truyền ngôi cho ai vào tháng 10 năm 1224?
- **Rewrite (blind):** Huệ Tông đã nhường ngôi cho ai vào cuối năm 1224?
- **Answer:** Chiêu Thánh công chúa
- **Evidence:** Tháng 10 năm giáp-thân (1224) Huệ-tông truyền ngôi cho Chiêu-thánh công-chúa, rồi vào ở chùa Chân-giáo.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c332-seen  (Quyển I > Phần III > Chương XV: Nhà Lê)

- **Question (seen):** Theo quy định của nhà Lê, ai có trách nhiệm lập bia cấm con trai con gái tắm chung một bến?
- **Rewrite (blind):** Ai lo việc dựng bia cấm nam nữ tắm chung bến theo luật nhà Lê?
- **Answer:** Phủ huyện
- **Evidence:** Phủ huyện phải lập bia ở các nơi sở-tại để cấm con-trai con-gái không được cùng tắm một bến, để cho có phân biệt.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c292-seen  (Quyển I > Phần III > Chương XIV: Mười năm đánh quân Tàu)

- **Question (seen):** Trận Tụy Động diễn ra vào tháng nào, năm nào?
- **Rewrite (blind):** Trận Tụy Động xảy ra vào thời gian nào?
- **Answer:** Tháng mười năm Bính Ngọ (1426)
- **Evidence:** Trận Tụy-động đánh vào tháng mười năm bính-ngọ (1426).
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c56-seen  (Quyển I > Phần II > Chương III: Bắc Thuộc lần thứ hai)

- **Question (seen):** Triệu Thị Chinh quê ở huyện nào?
- **Rewrite (blind):** Triệu Thị Chinh sinh ra ở đâu?
- **Answer:** Huyện Nông Cống
- **Evidence:** Sử ta chép rằng bà Triệu là người huyện Nông-cống bấy giờ.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c201-seen  (Quyển I > Phần III > Chương VIII: Giặc nhà Nguyên - II)

- **Question (seen):** Ai là người đã bày mưu cho vua Nhân Tông giết Ô Mã Nhi?
- **Rewrite (blind):** Người nào đã hiến kế để vua Nhân Tông xử tử Ô Mã Nhi?
- **Answer:** Hưng Đạo Vương
- **Evidence:** Duy có Ô mã Nhi giết hại nhiều người, vua căm-tức vô cùng, không muốn tha về, nhưng lại ngại đường hòa-hiếu, bèn dùng mưu của Hưng-đạo-vương sai người đưa đi đến giữa bể, đánh đắm thuyền, cho chết đuối, mà Nguyên-triều cũng không trách vào đâu được.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c241-seen  (Quyển I > Phần III > Chương X: Nhà Trần (Thời kỳ thứ ba))

- **Question (seen):** Lê Quý Ly tự xưng làm vua thay ngôi nhà Trần vào năm nào?
- **Rewrite (blind):** Lê Quý Ly lên ngôi thay nhà Trần lúc nào?
- **Answer:** Năm 1400
- **Evidence:** Đến tháng hai năm canh-thìn (1400) Quí Ly bỏ Thiếu-đế rồi tự xưng làm vua thay ngôi nhà Trần.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c93-seen  (Quyển I > Phần II > Chương VI: Kết quả của thời đại Bắc Thuộc)

- **Question (seen):** Đức Thích Ca Mâu Ni là con của gia đình nào ở Ấn Độ?
- **Rewrite (blind):** Đức Phật Thích Ca Mâu Ni xuất thân từ gia đình nào tại Ấn Độ?
- **Answer:** Ngài là con một nhà quý tộc đất Ấn Độ.
- **Evidence:** Đức Thích-ca là con một nhà quí-tộc đất Ấn-độ.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c297-seen  (Quyển I > Phần III > Chương XIV: Mười năm đánh quân Tàu)

- **Question (seen):** Ai đã bị giết trong trận Mỹ Động khi đi cứu Lê Nguyễn?
- **Rewrite (blind):** Ai bị giết ở trận Mỹ Động khi tới cứu Lê Nguyễn?
- **Answer:** Đinh Lễ
- **Evidence:** Vương Thông thấy quân Đinh Lễ có ít, bèn vây lại đánh bắt được Đinh Lễ và Nguyễn Xí. Nguyễn Xí trốn đi được, còn Đinh Lễ bị giết.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c219-seen  (Quyển I > Phần III > Chương X: Nhà Trần (Thời kỳ thứ ba))

- **Question (seen):** Ai là người đã lập nên vua Trần Dụ Tông?
- **Rewrite (blind):** Ai đã đưa Trần Dụ Tông lên ngôi vua?
- **Answer:** Minh Tông thượng hoàng
- **Evidence:** Hiến-tông không có con, Minh-tông thượng-hoàng lập người em tên là Hạo lên làm vua, tức là vua Dụ-tông.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound

### c173-seen  (Quyển I > Phần III > Chương VII: Giặc nhà Nguyên - I)

- **Question (seen):** Hưng Đạo vương đã soạn ra tác phẩm nào trước khi truyền hịch khuyên răn các tướng sĩ?
- **Rewrite (blind):** Hưng Đạo vương viết tác phẩm gì trước khi đưa ra bài hịch khuyên bảo tướng sĩ?
- **Answer:** Binh thư yếu lược
- **Evidence:** Bấy giờ Hưng-đạo vương có soạn ra một quyển Binh-thư yếu-lược rồi truyền hịch khuyên-răn các tướng-sĩ.
- **LLM verdict (Claude):** pass on (a)-(d).
- **Human verdict (user):** sound


## Human check

Done 2026-11-10 by the user, walked through each entry in chat (d48465 showed each pair, the problem and the proposed action; the user chose). Recorded separately from the LLM review above.

- **Flagged pairs (24):** the user confirmed all 24 flags. 7 dropped (c6, c16, c144, c177, c185, c310, c331); 17 fixed. On 3 the user chose a different action from the LLM's first proposal: c6 dropped instead of reworded (the reword was forced), c89 narrowed to how to treat others, c230 reduced to "who proposed it" because the book gives no date or king.
- **Control pairs (10):** the user found all 10 sound; the LLM review missed none of them.
- **Not checked:** the 25 unanswerable questions.
- **Result:** 208 seen/blind pairs, committed as `experiments/book-testset/questions.jsonl`. Rows changed by this review carry `"edited": "#178 review"`.
