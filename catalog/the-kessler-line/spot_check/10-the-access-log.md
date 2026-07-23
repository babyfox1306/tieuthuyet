---
series: the-kessler-line
book: 1
chapter: 10
title: The Access Log
spice: 1
word_count: 1953
status: draft
needs_fix: []
promoted_at: '2026-07-19T02:36:47Z'
---

Iris Kane stared at the two documents on her desk: the fast-track approval from Alan Watters, and the lab report detailing Dov Marek's forged certification. Both had Theo Vance's digital fingerprint. She knew what she needed next.

The terminal logs.

She had spent the drive back from the park bench turning over every possible way to access them without triggering an alert. Official request would land on the secretariat's desk within hours. Too visible. Too slow. Someone would ask questions before she had answers.

But IT archives were different. The commission's network had grown patchwork over fifteen years, with legacy systems that no one remembered to secure. She had seen it during her first week—a junior technician had left a shared drive open to the entire floor, containing shift schedules, password reset forms, and terminal assignment histories going back five years. She had mentioned it to no one.

That was her way in.

She pulled her coat on and grabbed the envelope with the fast-track document. The lab report stayed in her bag. She locked her office and took the stairs instead of the elevator, moving through the lower corridor where the fluorescent lights buzzed in uneven intervals.

The IT annex occupied a windowless corner of the second sublevel. The door required a badge, but the lock had been temperamental for months. She pressed her badge against the reader. The light stayed red. She pressed again. Nothing.

She could have turned back. The sensible part of her, the part that had survived twenty years in engineering by following procedure, told her to walk away. But the sensible part had already signed a dissent that would end her career the moment the report went final. There was nothing left to protect.

She pulled a thin metal shim from her coat pocket—a maintenance tool she had kept from her site inspection days—and slid it between the door and the frame. The latch clicked. She pushed through.

The server room hummed with the dry, metallic smell of aged electronics. Racks lined both walls, green lights blinking in orderly rows. At the far end, a single workstation sat beneath a flickering fluorescent tube. The screen was dark.

She crossed to the workstation and touched the mouse. The monitor woke to a login prompt. The system was still logged into a generic IT account—someone had left their session open. Classic oversight.

She opened the shared drive first. The folder structure was chaotic: dated by year, then by month, then by whatever the technician had typed into the file name. She navigated to the terminal assignment logs. Excel spreadsheets, each labeled with a date range. She downloaded the one covering the period of the fast-track approval—three months before the collapse.

The spreadsheet listed each terminal ID, the assigned user, the date of assignment, and notes. Terminal 47B was listed next to a name that made her chest tighten.

Theo Vance.

She scrolled further. The same terminal appeared in the subsequent month's log, and the month after that. No reassignment. No note about shared access.

She cross-referenced the timestamps from the fast-track document. The approval had been logged at 14:32 on a Thursday. Terminal 47B had been active that entire afternoon, with the first keystroke logged at 08:12 and the last at 17:49.

She opened the system access logs for the document management platform. The commission used a basic relational database with minimal security—any authenticated terminal could create, modify, or delete records without secondary approval. She queried the records for the fast-track document: creation timestamp, modifier ID, and the terminal IP.

The result lined up perfectly. Terminal 47B, user ID TVance, created the fast-track approval at 14:32. The forged certification had been entered twelve minutes later from the same terminal.

Iris sat back in the chair. The hum of the server room filled the silence.

She had known. Somewhere beneath the layers of professional courtesy and collegial trust, she had known. But seeing it in black and white, with timestamps and IP addresses, made it real in a way that suspicion never could.

She pulled a USB drive from her pocket and copied the logs. One copy. Two copies. Three. She would encrypt them, distribute them, bury them in places no one would think to search.

But she wasn't done.

The next folder on the shared drive contained server access records—logs of who had connected to the secure data storage where original load-test files were kept. She opened the file for the same period.

Terminal 47B again. A connection to the secure server at 09:17 on the morning after Marek's death. The user had navigated to the Kessler load-test directory. Multiple files had been viewed. And then, at 09:43, a bulk deletion command.

She checked the file names. All of them. The original load-test telemetry, the calibration certificates, the sensor calibration data—everything that could have proved the liner had never been certified for the actual load it was carrying.

The files were gone.

She searched for any backup copies. The system had a nightly archive, but the archive log showed no entries for that specific directory after the deletion. Someone had disabled the backup job for that folder two days before—another action from Terminal 47B.

Iris closed the log and rubbed her eyes. The numbers were starting to blur. She needed to see the full scope of what Vance had done.

She searched for internal memos originating from Vance's office. The document management system had a correspondence module, separate from the main repository, used for interdepartmental communication. She queried for memos sent by Vance in the six months before the collapse.

More than two hundred results.

She refined the search: memos containing keywords related to the Kessler contract, certification, or the liner itself. Seventeen results.

She opened the first one. Dated four months before the collapse. Subject: "Re-certification request — Kessler Line eastbound segment."

The body was brief. It requested that the Vantor site inspection team be authorized to bypass standard re-certification procedures due to scheduling pressure. The memo was addressed to the engineering oversight committee, copied to Alan Watters at Vantor.

Iris opened the attachment. A PDF of the same expedited re-certification order she had seen in the fast-track document, but with an earlier date. The signature block was different—a name she didn't recognize, someone in Vantor's compliance department who had since left the company.

She opened the next memo. Similar language. The third one included a handwritten note scanned as an image: "“Marek disagrees. Too risky. Needs to be overridden.”" The handwriting matched the annotations on the fast-track document.

Vance had known about Marek's objections. He had overridden them.

She opened the fourth memo. This one was addressed to someone outside the commission—a name she didn't recognize. The subject line read "“Confidential: Kessler timeline — proposed sequencing.”"

She read the first paragraph. It outlined a phased release of certifications, starting with a modified dispatch protocol, then a revised maintenance schedule, then a final inspection report. It was a schedule. A schedule for when each piece of evidence would surface, and when it would be buried.

Iris scrolled to the bottom. The memo was signed by Theo Vance.

She copied the entire correspondence repository. The USB drive filled rapidly—tens of thousands of pages of emails, memos, and internal notes. She didn't have time to read it all now. She would take it home, sort through it, find the connections.

But the pattern was already forming.

Vance hadn't just approved the fast-track. He had designed the entire information management strategy around the collapse. He had controlled what the public saw, what the commission reviewed, what the investigators were allowed to find.

And he had done it from a terminal in his office, using a system that everyone assumed was secure.

Iris unplugged the USB drive and slipped it into her inside pocket. She closed the shared drive, cleared the browser history, and logged out of the IT account. The server room hummed behind her as she moved toward the door.

The lock clicked shut as she pulled it closed. She took the stairs back to her floor, her footsteps echoing in the empty stairwell.

Back in her office, she locked the door and sat down. The USB drive was warm against her chest. She pulled out her personal laptop—not the commission-issued one—and inserted the drive.

The file list appeared. She opened the terminal access logs first. The spreadsheet was dense, but she knew exactly which rows to highlight.

Theo Vance's terminal ID appeared seventy-three times in the three months before the collapse. Thirty-seven of those were during off-hours. Eighteen were after midnight.

She opened the secure server access logs. The same pattern: late-night connections, file views, deletions. The load-test data had been wiped at 02:44 on a Sunday morning. No one had questioned it.

She opened the memos next. She scanned each one, looking for names, dates, references to the load-test failure. The correspondence painted a picture of a man who had known everything: the certification gap, the faulty liner, the risk of collapse. And who had chosen to bury it.

Iris leaned back in her chair. The office was dark except for the glow of her laptop screen. Somewhere outside, the city was waking up. But here, inside the commission building, the evidence was laid out in front of her.

She scrolled to the last memo in the repository. It was dated the day after the collapse. Subject line: "Revised terms of reference."

The memo proposed a new inquiry structure. One that would limit the scope of the investigation, control the flow of evidence, and ensure that the official cause remained within acceptable parameters. The memo was addressed to the minister's office.

The final line read: "“Approved as submitted — AR.”"

Aldous Renn.

Iris stared at the initials. She had known Renn was involved at a high level. But this memo placed him directly in the chain of command, approving the inquiry framework that had been designed to contain the truth.

She needed to see more. She needed to understand how high the chain went.

Her phone buzzed. A text from an unknown number.

"Stop now. You have enough."

She read the message twice. The number was not in her contacts. She did not respond. Instead, she pulled the USB drive, locked it in her personal safe, and turned back to her laptop.

The notification banner remained on her screen. She closed it without thinking.

The evidence was in her hands. The terminal logs, the memos, the timestamps. She had what she needed.

But the message told her something else: they knew. They knew she had accessed the logs. They knew she had the evidence.

The question was how long she had before they came for it.

She scrolled through the log entries one more time, her mouse hovering over the final row. The truth was worse than she imagined. Theo Vance hadn't just helped a corrupt contractor cover up a fatal defect. He had built the system that made it possible. He had designed the inquiry that was supposed to uncover it. He had worked with someone at the highest levels of government to ensure that the truth would never reach the public.

And he had used his own office, his own terminal, his own login to do it.

Iris Kane closed the laptop and sat in the dark, the weight of what she had discovered pressing down on her shoulders. The clock on the wall read 4:17 AM. There was no going back to the person she had been the day before.

She had found the access log. She had the proof.

But the proof was only useful if she stayed alive long enough to use it.