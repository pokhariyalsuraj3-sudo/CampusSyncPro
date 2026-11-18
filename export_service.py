import io
import re
import calendar
from datetime import datetime
from openpyxl import Workbook
from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
from openpyxl.utils import get_column_letter

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.units import inch, cm
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.platypus import (
    SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, KeepTogether
)
from reportlab.pdfgen import canvas

# ==============================================================================
# 1. FILENAME GENERATOR
# ==============================================================================

def generate_export_filename(class_name, subject_name, month_name, year, extension):
    """
    Builds a clean, descriptive filename without spaces or illegal characters.
    Example: CampusSync_Attendance_3rdYearIT_JavaProgramming_November_2026.pdf
    """
    def clean(token):
        if not token:
            return ""
        # Remove non-alphanumeric characters but preserve casing
        return re.sub(r'[^a-zA-Z0-9]+', '', str(token))

    c_part = clean(class_name) or "Class"
    s_part = clean(subject_name) if subject_name else ""
    m_part = clean(month_name) or "Month"
    y_part = str(year)

    parts = ["CampusSync", "Attendance", c_part]
    if s_part and s_part.lower() not in ("all", "nosubjectsassigned"):
        parts.append(s_part)
    parts.extend([m_part, y_part])

    ext = extension.lstrip('.')
    return "_".join(parts) + f".{ext}"


# ==============================================================================
# 2. EXCEL EXPORT ENGINE (openpyxl)
# ==============================================================================

def generate_attendance_excel(class_info, subject_info, year, month, days, session_dates, students, summary):
    """
    Generates a native .xlsx workbook with complete styling, frozen panes,
    formatted percentages, header colors, borders, and print configuration.
    Returns: io.BytesIO buffer containing the workbook.
    """
    wb = Workbook()
    ws = wb.active
    month_name = calendar.month_name[month]
    ws.title = f"Attendance {month_name[:3]} {year}"
    ws.views.sheetView[0].showGridLines = True

    # Palette Definitions
    COLOR_BRAND_PURPLE = "4D3896"
    COLOR_BRAND_NAVY   = "1F1841"
    COLOR_LIGHT_PURPLE = "F6F3FC"
    COLOR_ACTIVE_DAY   = "6B46C1"
    COLOR_WEEKDAY_BG   = "ECE7FB"
    COLOR_PRESENT_BG   = "DCFCE7"
    COLOR_PRESENT_TXT  = "15803D"
    COLOR_ABSENT_BG    = "FEE2E2"
    COLOR_ABSENT_TXT   = "B91C1C"
    COLOR_NONE_TXT     = "94A3B8"
    COLOR_BORDER_LIGHT = "E2E8F0"
    COLOR_BORDER_DARK  = "CBD5E1"

    font_title = Font(name="Segoe UI", size=15, bold=True, color=COLOR_BRAND_NAVY)
    font_subtitle = Font(name="Segoe UI", size=9, italic=True, color="64748B")
    font_meta_lbl = Font(name="Segoe UI", size=9, bold=True, color=COLOR_BRAND_PURPLE)
    font_meta_val = Font(name="Segoe UI", size=9, bold=False, color="1E293B")
    font_kpi_lbl = Font(name="Segoe UI", size=8, bold=True, color="475569")
    font_kpi_val = Font(name="Segoe UI", size=10, bold=True, color=COLOR_BRAND_NAVY)
    font_th = Font(name="Segoe UI", size=9, bold=True, color="FFFFFF")
    font_th_sub = Font(name="Segoe UI", size=8, bold=True, color=COLOR_BRAND_NAVY)
    font_data = Font(name="Segoe UI", size=9)
    font_roll = Font(name="Consolas", size=9)
    font_p = Font(name="Segoe UI", size=9, bold=True, color=COLOR_PRESENT_TXT)
    font_a = Font(name="Segoe UI", size=9, bold=True, color=COLOR_ABSENT_TXT)
    font_none = Font(name="Segoe UI", size=9, color=COLOR_NONE_TXT)

    fill_header = PatternFill(start_color=COLOR_BRAND_PURPLE, end_color=COLOR_BRAND_PURPLE, fill_type="solid")
    fill_header_session = PatternFill(start_color=COLOR_ACTIVE_DAY, end_color=COLOR_ACTIVE_DAY, fill_type="solid")
    fill_sub_header = PatternFill(start_color=COLOR_WEEKDAY_BG, end_color=COLOR_WEEKDAY_BG, fill_type="solid")
    fill_kpi = PatternFill(start_color=COLOR_LIGHT_PURPLE, end_color=COLOR_LIGHT_PURPLE, fill_type="solid")
    fill_p = PatternFill(start_color=COLOR_PRESENT_BG, end_color=COLOR_PRESENT_BG, fill_type="solid")
    fill_a = PatternFill(start_color=COLOR_ABSENT_BG, end_color=COLOR_ABSENT_BG, fill_type="solid")
    fill_zebra = PatternFill(start_color="F8FAFC", end_color="F8FAFC", fill_type="solid")

    thin_border = Border(
        left=Side(style='thin', color=COLOR_BORDER_LIGHT),
        right=Side(style='thin', color=COLOR_BORDER_LIGHT),
        top=Side(style='thin', color=COLOR_BORDER_LIGHT),
        bottom=Side(style='thin', color=COLOR_BORDER_LIGHT)
    )
    th_border = Border(
        left=Side(style='thin', color=COLOR_BORDER_DARK),
        right=Side(style='thin', color=COLOR_BORDER_DARK),
        top=Side(style='medium', color=COLOR_BRAND_PURPLE),
        bottom=Side(style='medium', color=COLOR_BRAND_PURPLE)
    )

    align_center = Alignment(horizontal="center", vertical="center")
    align_left = Alignment(horizontal="left", vertical="center")
    align_right = Alignment(horizontal="right", vertical="center")

    class_name = class_info.get('name', 'General Class') if class_info else "General Class"
    branch_name = class_info.get('branch', 'Information Technology') if class_info else "Information Technology"
    subject_name = subject_info.get('name', 'All Enrolled Subjects') if subject_info else "All Enrolled Subjects"
    gen_time_str = datetime.now().strftime('%d-%b-%Y %I:%M %p')

    # Row 1: Title
    ws.merge_cells("A1:K1")
    ws["A1"] = "CampusSync — Overall Attendance Register"
    ws["A1"].font = font_title
    ws["A1"].alignment = align_left
    ws.row_dimensions[1].height = 24

    # Row 2: Subtitle
    ws.merge_cells("A2:K2")
    ws["A2"] = "Official Academic Monthly Attendance Matrix & Verification Register"
    ws["A2"].font = font_subtitle
    ws["A2"].alignment = align_left
    ws.row_dimensions[2].height = 16

    # Row 3: Metadata Block
    meta_pairs = [
        ("A3", "B3", "Class / Batch:", class_name),
        ("C3", "D3", "Subject:", subject_name),
        ("E3", "F3", "Branch:", branch_name),
        ("G3", "H3", "Period:", f"{month_name} {year}"),
        ("I3", "K3", "Generated:", gen_time_str)
    ]
    for lbl_col, val_col, lbl, val in meta_pairs:
        ws[lbl_col] = lbl
        ws[lbl_col].font = font_meta_lbl
        ws[lbl_col].alignment = align_left
        ws[val_col] = val
        ws[val_col].font = font_meta_val
        ws[val_col].alignment = align_left
    ws.row_dimensions[3].height = 18

    # Row 4: Summary KPIs
    kpis = [
        ("A4", "B4", "Students:", summary.get('total_students', len(students))),
        ("C4", "D4", "Conducted Lectures:", summary.get('total_sessions', len(session_dates))),
        ("E4", "F4", "Total Present Marks:", summary.get('total_present', 0)),
        ("G4", "H4", "Total Absent Marks:", summary.get('total_absent', 0)),
        ("I4", "K4", "Class Average:", f"{summary.get('avg_attendance_pct', 0.0)}%")
    ]
    for lbl_col, val_col, lbl, val in kpis:
        ws[lbl_col] = lbl
        ws[lbl_col].font = font_kpi_lbl
        ws[lbl_col].fill = fill_kpi
        ws[lbl_col].alignment = align_left
        ws[val_col] = val
        ws[val_col].font = font_kpi_val
        ws[val_col].fill = fill_kpi
        ws[val_col].alignment = align_left
    ws.row_dimensions[4].height = 20

    # Row 5: Empty space
    ws.row_dimensions[5].height = 8

    # Table Header Rows: Row 6 (Days) & Row 7 (Weekdays)
    ws.row_dimensions[6].height = 22
    ws.row_dimensions[7].height = 18

    fixed_headers = [
        (1, "#"),
        (2, "Roll Number"),
        (3, "Student Name")
    ]
    for col_idx, label in fixed_headers:
        ws.cell(row=6, column=col_idx, value=label).font = font_th
        ws.cell(row=6, column=col_idx).fill = fill_header
        ws.cell(row=6, column=col_idx).alignment = align_center
        ws.cell(row=6, column=col_idx).border = th_border

        ws.cell(row=7, column=col_idx, value="").font = font_th_sub
        ws.cell(row=7, column=col_idx).fill = fill_sub_header
        ws.cell(row=7, column=col_idx).alignment = align_center
        ws.cell(row=7, column=col_idx).border = th_border

        # Merge fixed header across row 6 and 7
        ws.merge_cells(start_row=6, start_column=col_idx, end_row=7, end_column=col_idx)

    curr_col = 4
    for d in days:
        day_num = d['day']
        wday = d['weekday']
        has_session = d.get('has_session', False)

        cell_d = ws.cell(row=6, column=curr_col, value=f"{day_num:02d}")
        cell_d.font = font_th
        cell_d.fill = fill_header_session if has_session else fill_header
        cell_d.alignment = align_center
        cell_d.border = th_border

        cell_w = ws.cell(row=7, column=curr_col, value=wday)
        cell_w.font = font_th_sub
        cell_w.fill = fill_sub_header
        cell_w.alignment = align_center
        cell_w.border = th_border
        curr_col += 1

    summary_headers = [
        (curr_col, "Present (P)"),
        (curr_col + 1, "Absent (A)"),
        (curr_col + 2, "Attendance %")
    ]
    for col_idx, label in summary_headers:
        ws.cell(row=6, column=col_idx, value=label).font = font_th
        ws.cell(row=6, column=col_idx).fill = fill_header
        ws.cell(row=6, column=col_idx).alignment = align_center
        ws.cell(row=6, column=col_idx).border = th_border

        ws.cell(row=7, column=col_idx, value="").font = font_th_sub
        ws.cell(row=7, column=col_idx).fill = fill_sub_header
        ws.cell(row=7, column=col_idx).alignment = align_center
        ws.cell(row=7, column=col_idx).border = th_border
        ws.merge_cells(start_row=6, start_column=col_idx, end_row=7, end_column=col_idx)

    # Data Rows (Row 8+)
    row_num = 8
    for idx, st in enumerate(students, start=1):
        ws.row_dimensions[row_num].height = 19
        zebra = (idx % 2 == 0)

        # Col 1: Index
        c1 = ws.cell(row=row_num, column=1, value=idx)
        c1.font = font_data
        c1.alignment = align_center
        c1.border = thin_border
        if zebra: c1.fill = fill_zebra

        # Col 2: Roll Number
        c2 = ws.cell(row=row_num, column=2, value=st.get('roll_number') or "Not Assigned")
        c2.font = font_roll
        c2.alignment = align_left
        c2.border = thin_border
        if zebra: c2.fill = fill_zebra

        # Col 3: Student Name
        c3 = ws.cell(row=row_num, column=3, value=st.get('full_name') or "Unknown Student")
        c3.font = font_data
        c3.alignment = align_left
        c3.border = thin_border
        if zebra: c3.fill = fill_zebra

        # Daily Matrix
        c_idx = 4
        matrix = st.get('matrix', {})
        for d in days:
            val = matrix.get(d['date_str'], '-')
            cell = ws.cell(row=row_num, column=c_idx, value=val)
            cell.alignment = align_center
            cell.border = thin_border

            if val == 'P':
                cell.font = font_p
                cell.fill = fill_p
            elif val == 'A':
                cell.font = font_a
                cell.fill = fill_a
            else:
                cell.font = font_none
                if zebra: cell.fill = fill_zebra
            c_idx += 1

        # Present Count
        c_p = ws.cell(row=row_num, column=c_idx, value=st.get('total_present', 0))
        c_p.font = font_p
        c_p.alignment = align_center
        c_p.border = thin_border
        c_p.fill = PatternFill(start_color="F0FDF4", end_color="F0FDF4", fill_type="solid")

        # Absent Count
        c_a = ws.cell(row=row_num, column=c_idx + 1, value=st.get('total_absent', 0))
        c_a.font = font_a
        c_a.alignment = align_center
        c_a.border = thin_border
        c_a.fill = PatternFill(start_color="FEF2F2", end_color="FEF2F2", fill_type="solid")

        # Attendance Percentage
        pct_val = st.get('attendance_pct', 0.0)
        c_pct = ws.cell(row=row_num, column=c_idx + 2, value=f"{pct_val:.1f}%")
        c_pct.font = font_data
        c_pct.alignment = align_center
        c_pct.border = thin_border
        c_pct.fill = PatternFill(start_color="FAF8FF", end_color="FAF8FF", fill_type="solid")

        row_num += 1

    # Freeze identity columns (A, B, C) and top headers (Rows 1-7)
    ws.freeze_panes = "D8"

    # Column Width Optimization
    ws.column_dimensions['A'].width = 5
    ws.column_dimensions['B'].width = 16
    ws.column_dimensions['C'].width = 28
    for c_i in range(4, 4 + len(days)):
        ws.column_dimensions[get_column_letter(c_i)].width = 5.2
    ws.column_dimensions[get_column_letter(curr_col)].width = 13
    ws.column_dimensions[get_column_letter(curr_col + 1)].width = 13
    ws.column_dimensions[get_column_letter(curr_col + 2)].width = 15

    # Page Setup for Printing
    ws.page_setup.orientation = ws.ORIENTATION_LANDSCAPE
    ws.page_setup.paperSize = ws.PAPERSIZE_A4
    ws.page_setup.fitToPage = True
    ws.page_setup.fitToWidth = 1
    ws.page_setup.fitToHeight = 0
    ws.sheet_properties.pageSetUpPr.fitToPage = True
    ws.print_title_rows = "6:7"

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    return output


# ==============================================================================
# 3. PDF EXPORT ENGINE (reportlab)
# ==============================================================================

class NumberedCanvas(canvas.Canvas):
    """
    Two-pass canvas that dynamically counts total pages and draws
    professional running headers and footers with 'Page X of Y'.
    """
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._saved_page_states = []

    def showPage(self):
        self._saved_page_states.append(dict(self.__dict__))
        self._startPage()

    def save(self):
        num_pages = len(self._saved_page_states)
        for state in self._saved_page_states:
            self.__dict__.update(state)
            self.draw_page_decorations(num_pages)
            super().showPage()
        super().save()

    def draw_page_decorations(self, page_count):
        self.saveState()
        self.setFont("Helvetica", 7.5)
        self.setFillColor(colors.HexColor("#64748B"))

        # Footer (Running on all pages)
        footer_y = 14
        self.drawString(24, footer_y, "CampusSync Digital College Portal • Official Attendance Record")
        page_str = f"Page {self._pageNumber} of {page_count}"
        self.drawRightString(841.89 - 24, footer_y, page_str)

        # Thin footer rule
        self.setStrokeColor(colors.HexColor("#E2E8F0"))
        self.setLineWidth(0.5)
        self.line(24, footer_y + 9, 841.89 - 24, footer_y + 9)

        # Running header on page 2 and beyond
        if self._pageNumber > 1:
            header_y = 595.27 - 16
            self.drawString(24, header_y, "CampusSync — Overall Attendance Register")
            self.drawRightString(841.89 - 24, header_y, "Confidential • Internal Academic Record")
            self.setStrokeColor(colors.HexColor("#CBD5E1"))
            self.setLineWidth(0.5)
            self.line(24, header_y - 4, 841.89 - 24, header_y - 4)

        self.restoreState()


def generate_attendance_pdf(class_info, subject_info, year, month, days, session_dates, students, summary):
    """
    Generates a printable, publication-quality PDF attendance report in Landscape A4.
    Repeats table headers on page breaks and highlights active lecture sessions.
    Returns: io.BytesIO buffer containing the PDF document.
    """
    buffer = io.BytesIO()
    month_name = calendar.month_name[month]
    class_name = class_info.get('name', 'General Class') if class_info else "General Class"
    branch_name = class_info.get('branch', 'Information Technology') if class_info else "Information Technology"
    academic_year = class_info.get('academic_year', '') if class_info else ""
    subject_name = subject_info.get('name', 'All Enrolled Subjects') if subject_info else "All Enrolled Subjects"
    gen_time_str = datetime.now().strftime('%d-%b-%Y %I:%M %p')

    # Page Geometry: Landscape A4 is 841.89 x 595.27 points
    # Printable area: 841.89 - 48 = 793.89 pt horizontally; 595.27 - (36 + 32) = 527.27 pt vertically
    doc = SimpleDocTemplate(
        buffer,
        pagesize=landscape(A4),
        leftMargin=24,
        rightMargin=24,
        topMargin=36,
        bottomMargin=32
    )

    styles = getSampleStyleSheet()
    story = []

    # 1. Header Banner Box
    title_style = ParagraphStyle(
        'DocTitle',
        parent=styles['Normal'],
        fontName='Helvetica-Bold',
        fontSize=13,
        leading=16,
        textColor=colors.HexColor('#FFFFFF')
    )
    subtitle_style = ParagraphStyle(
        'DocSubtitle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=8,
        leading=10,
        textColor=colors.HexColor('#E2DCF7')
    )
    meta_style_left = ParagraphStyle(
        'MetaLeft',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10,
        textColor=colors.HexColor('#FFFFFF')
    )
    meta_style_right = ParagraphStyle(
        'MetaRight',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=10,
        alignment=2,  # Right aligned
        textColor=colors.HexColor('#FFFFFF')
    )

    header_data = [
        [
            Paragraph("<b>CampusSync — Overall Attendance Register</b>", title_style),
            Paragraph(f"<b>Period:</b> {month_name} {year}", meta_style_right)
        ],
        [
            Paragraph(f"<b>Class:</b> {class_name} &nbsp;|&nbsp; <b>Branch:</b> {branch_name} {f'({academic_year})' if academic_year else ''} &nbsp;|&nbsp; <b>Subject:</b> {subject_name}", meta_style_left),
            Paragraph(f"<b>Generated:</b> {gen_time_str}", meta_style_right)
        ]
    ]

    header_table = Table(header_data, colWidths=[550, 243.89])
    header_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#31226A')),
        ('TOPPADDING', (0, 0), (-1, -1), 4),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 4),
        ('LEFTPADDING', (0, 0), (-1, -1), 8),
        ('RIGHTPADDING', (0, 0), (-1, -1), 8),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('CORNERPAD', (0, 0), (-1, -1), 4)
    ]))
    story.append(header_table)
    story.append(Spacer(1, 4))

    # 2. KPI Summary Bar
    kpi_style = ParagraphStyle(
        'KPIStyle',
        parent=styles['Normal'],
        fontName='Helvetica',
        fontSize=7.5,
        leading=9,
        alignment=1,  # Centered
        textColor=colors.HexColor('#1F1841')
    )
    tot_st = summary.get('total_students', len(students))
    tot_sess = summary.get('total_sessions', len(session_dates))
    tot_p = summary.get('total_present', 0)
    tot_a = summary.get('total_absent', 0)
    avg_pct = summary.get('avg_attendance_pct', 0.0)

    kpi_data = [[
        Paragraph(f"Students Enrolled: <b>{tot_st}</b>", kpi_style),
        Paragraph(f"Lectures Conducted: <b>{tot_sess}</b>", kpi_style),
        Paragraph(f"Total Present Marks: <b><font color='#15803D'>{tot_p}</font></b>", kpi_style),
        Paragraph(f"Total Absent Marks: <b><font color='#B91C1C'>{tot_a}</font></b>", kpi_style),
        Paragraph(f"Class Average: <b>{avg_pct}%</b>", kpi_style),
        Paragraph("Legend: <font color='#15803D'><b>P</b></font>=Present &nbsp; <font color='#B91C1C'><b>A</b></font>=Absent &nbsp; <font color='#94A3B8'><b>—</b></font>=No Session", kpi_style)
    ]]
    kpi_table = Table(kpi_data, colWidths=[95, 95, 105, 105, 95, 298.89])
    kpi_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -1), colors.HexColor('#F6F3FC')),
        ('TOPPADDING', (0, 0), (-1, -1), 3),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 3),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('BOX', (0, 0), (-1, -1), 0.5, colors.HexColor('#E2DCF7'))
    ]))
    story.append(kpi_table)
    story.append(Spacer(1, 5))

    # 3. Main Attendance Matrix Table
    # Printable area: 841.89 - 48 = 793.89 pt
    num_days = len(days)
    col_idx_w = 16
    col_roll_w = 62
    col_name_w = 116
    col_p_w = 25
    col_a_w = 25
    col_pct_w = 34
    fixed_total_w = col_idx_w + col_roll_w + col_name_w + col_p_w + col_a_w + col_pct_w
    avail_for_days = 793.89 - fixed_total_w
    day_w = round(avail_for_days / num_days, 2)
    day_widths = [day_w] * (num_days - 1) + [round(avail_for_days - day_w * (num_days - 1), 2)]

    col_widths = [col_idx_w, col_roll_w, col_name_w] + day_widths + [col_p_w, col_a_w, col_pct_w]

    th_main_style = ParagraphStyle('THM', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=6.0, leading=7.0, alignment=1, textColor=colors.white)
    th_sub_style  = ParagraphStyle('THS', parent=styles['Normal'], fontName='Helvetica-Bold', fontSize=5.5, leading=6.5, alignment=1, textColor=colors.HexColor('#1F1841'))
    td_text_style = ParagraphStyle('TDT', parent=styles['Normal'], fontName='Helvetica', fontSize=6.2, leading=7.2, alignment=0, textColor=colors.HexColor('#1E293B'))
    td_roll_style = ParagraphStyle('TDR', parent=styles['Normal'], fontName='Helvetica', fontSize=5.8, leading=6.8, alignment=0, textColor=colors.HexColor('#0F172A'))

    # Header Row 1: Day numbers
    row1 = [
        Paragraph("<b>#</b>", th_main_style),
        Paragraph("<b>Roll No</b>", th_main_style),
        Paragraph("<b>Student Name</b>", th_main_style)
    ]
    for d in days:
        row1.append(Paragraph(f"<b>{d['day']}</b>", th_main_style))
    row1.extend([
        Paragraph("<b>P</b>", th_main_style),
        Paragraph("<b>A</b>", th_main_style),
        Paragraph("<b>%</b>", th_main_style)
    ])

    # Header Row 2: Weekday single-letter
    row2 = ["", "", ""]
    for d in days:
        w = d['weekday'][:1] # S, M, T, W, T, F, S
        row2.append(Paragraph(f"<b>{w}</b>", th_sub_style))
    row2.extend(["", "", ""])

    table_data = [row1, row2]

    # Data Rows
    for idx, st in enumerate(students, start=1):
        s_name = st.get('full_name') or "Unknown Student"
        if len(s_name) > 30:
            s_name = s_name[:28] + "…"
        s_roll = st.get('roll_number') or "—"
        if len(s_roll) > 16:
            s_roll = s_roll[:14] + "…"

        row = [
            str(idx),
            Paragraph(s_roll, td_roll_style),
            Paragraph(s_name, td_text_style)
        ]

        matrix = st.get('matrix', {})
        for d in days:
            v = matrix.get(d['date_str'], '-')
            row.append(v)

        row.append(str(st.get('total_present', 0)))
        row.append(str(st.get('total_absent', 0)))
        row.append(f"{st.get('attendance_pct', 0.0):.0f}%")
        table_data.append(row)

    # If no students enrolled
    if not students:
        table_data.append([
            "", "",
            Paragraph("<i>No students currently enrolled in this class/subject.</i>", td_text_style)
        ] + [""] * (num_days + 3))

    table_style = [
        # Top Header styling
        ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#4D3896')),
        ('BACKGROUND', (0, 1), (-1, 1), colors.HexColor('#ECE7FB')),
        ('ALIGN', (0, 0), (-1, 1), 'CENTER'),
        ('VALIGN', (0, 0), (-1, -1), 'MIDDLE'),
        ('TOPPADDING', (0, 0), (-1, -1), 1.5),
        ('BOTTOMPADDING', (0, 0), (-1, -1), 1.5),
        ('LEFTPADDING', (0, 0), (-1, -1), 1),
        ('RIGHTPADDING', (0, 0), (-1, -1), 1),
        ('INNERGRID', (0, 0), (-1, -1), 0.35, colors.HexColor('#CBD5E1')),
        ('BOX', (0, 0), (-1, -1), 0.75, colors.HexColor('#4D3896')),
        ('SPAN', (0, 0), (0, 1)),   # Span #
        ('SPAN', (1, 0), (1, 1)),   # Span Roll No
        ('SPAN', (2, 0), (2, 1)),   # Span Student Name
        ('SPAN', (-3, 0), (-3, 1)), # Span P
        ('SPAN', (-2, 0), (-2, 1)), # Span A
        ('SPAN', (-1, 0), (-1, 1)), # Span %
        ('FONTNAME', (0, 2), (0, -1), 'Helvetica'),
        ('FONTSIZE', (0, 2), (-1, -1), 6.0),
        ('ALIGN', (0, 2), (0, -1), 'CENTER'),
        ('ALIGN', (3, 2), (-1, -1), 'CENTER'),
        ('BACKGROUND', (-3, 2), (-3, -1), colors.HexColor('#F0FDF4')),
        ('BACKGROUND', (-2, 2), (-2, -1), colors.HexColor('#FEF2F2')),
        ('BACKGROUND', (-1, 2), (-1, -1), colors.HexColor('#FAF8FF')),
        ('TEXTCOLOR', (-3, 2), (-3, -1), colors.HexColor('#15803D')),
        ('TEXTCOLOR', (-2, 2), (-2, -1), colors.HexColor('#B91C1C'))
    ]

    # Highlight active session columns in header
    for c_idx, d in enumerate(days, start=3):
        if d.get('has_session', False):
            table_style.append(('BACKGROUND', (c_idx, 0), (c_idx, 0), colors.HexColor('#6B46C1')))

    # Alternating row colors
    for r_idx in range(2, len(table_data)):
        if r_idx % 2 == 1:
            table_style.append(('BACKGROUND', (0, r_idx), (2 + num_days, r_idx), colors.HexColor('#F8FAFC')))

    # Color code daily 'P', 'A', '-' cells
    for r_idx in range(2, len(table_data)):
        for c_idx in range(3, 3 + num_days):
            val = table_data[r_idx][c_idx]
            if val == 'P':
                table_style.append(('TEXTCOLOR', (c_idx, r_idx), (c_idx, r_idx), colors.HexColor('#15803D')))
                table_style.append(('FONTNAME', (c_idx, r_idx), (c_idx, r_idx), 'Helvetica-Bold'))
            elif val == 'A':
                table_style.append(('TEXTCOLOR', (c_idx, r_idx), (c_idx, r_idx), colors.HexColor('#B91C1C')))
                table_style.append(('FONTNAME', (c_idx, r_idx), (c_idx, r_idx), 'Helvetica-Bold'))
            else:
                table_style.append(('TEXTCOLOR', (c_idx, r_idx), (c_idx, r_idx), colors.HexColor('#94A3B8')))

    row_heights = [15, 13] + [15] * len(students if students else [1])
    main_table = Table(table_data, colWidths=col_widths, rowHeights=row_heights, repeatRows=2)
    main_table.setStyle(TableStyle(table_style))
    story.append(main_table)

    # Build PDF with two-pass canvas
    doc.build(story, canvasmaker=NumberedCanvas)
    buffer.seek(0)
    return buffer
