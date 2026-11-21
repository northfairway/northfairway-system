"""Shared report table formatting (presentation only; no accounting computations)."""
from xml.sax.saxutils import escape
from reportlab.lib import colors
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.enums import TA_RIGHT
from reportlab.platypus import LongTable, TableStyle, Paragraph
GREEN = colors.HexColor('#1B4332')
def text(value):
    return escape(str(value if value is not None else '-')).replace('\n','<br/>')
def report_table(headers, rows, widths, money_columns=(), font_size=7):
    normal=ParagraphStyle('NFHReportCell',fontName='Helvetica',fontSize=font_size,leading=font_size+2,spaceAfter=0)
    right=ParagraphStyle('NFHReportMoney',parent=normal,alignment=TA_RIGHT)
    heading=ParagraphStyle('NFHReportHeader',parent=normal,fontName='Helvetica-Bold',textColor=colors.white)
    data=[[Paragraph(text(x),heading) for x in headers]]
    for row in rows:
        data.append([Paragraph(text(value),right if index in money_columns else normal) for index,value in enumerate(row)])
    if not rows:
        data.append([Paragraph('No matching records',normal)]+[Paragraph('',normal) for _ in headers[1:]])
    t=LongTable(data,colWidths=widths,repeatRows=1,hAlign='LEFT',splitByRow=1)
    t.setStyle(TableStyle([('BACKGROUND',(0,0),(-1,0),GREEN),('ROWBACKGROUNDS',(0,1),(-1,-1),[colors.white,colors.HexColor('#F4F9F4')]),('VALIGN',(0,0),(-1,-1),'TOP'),('LEFTPADDING',(0,0),(-1,-1),6),('RIGHTPADDING',(0,0),(-1,-1),6),('TOPPADDING',(0,0),(-1,-1),6),('BOTTOMPADDING',(0,0),(-1,-1),6),('LINEBELOW',(0,0),(-1,-1),.2,colors.HexColor('#DDE5DE'))]))
    return t
def page_footer(canvas, doc):
    canvas.saveState()
    w,_=doc.pagesize
    canvas.setFont('Helvetica',8)
    canvas.setFillColor(colors.HexColor('#4A5E51'))
    canvas.drawString(doc.leftMargin,22,'North Fairway Homes Homeowners Association')
    canvas.drawRightString(w-doc.rightMargin,22,f'Page {doc.page}')
    canvas.restoreState()
