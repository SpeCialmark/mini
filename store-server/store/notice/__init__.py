import smtplib
import email
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.image import MIMEImage
from email.mime.base import MIMEBase
from email.mime.application import MIMEApplication
from store.config import cfg
from email.header import Header


def send_admin_email(subject, text):
    # from_name = cfg['notice_email']['from_name']
    from_name = '11练团队'
    admin_emails = cfg['notice_email']['admin_emails']
    recipients = list()
    recipients.extend(admin_emails)
    _send_email(recipients=recipients, subject=subject, from_name=from_name, text=text)


def send_experience_email(subject, text, recipient: list):
    from_name = '11练小程序'
    # recipient = ['243642677@qq.com']  # 目前只有美航
    recipients = list()
    recipients.extend(recipient)
    _send_email(recipients=recipient, subject=subject, from_name=from_name, text=text)
    return


def send_salesmen_email(subject, text, recipient: list):
    # 用于发送通知邮件给接待会籍
    from_name = '11练小程序'
    recipients = list()
    recipients.extend(recipient)
    _send_email(recipients=recipient, subject=subject, from_name=from_name, text=text)
    return


def _send_email(recipients, subject, from_name, text):
    # from_name 发件人
    # recipients 收件人
    # subject 邮件标题
    # text 通知文本
    username = cfg['notice_email']['username']
    password = cfg['notice_email']['password']

    # 构建alternative结构
    msg = MIMEMultipart('alternative')
    msg['Subject'] = Header(subject)
    msg['From'] = '%s <%s>' % (Header(from_name), username)
    msg['To'] = ", ".join(recipients)
    msg['Reply-to'] = ''
    msg['Message-id'] = email.utils.make_msgid()
    msg['Date'] = email.utils.formatdate()
    # 构建alternative的text/plain部分
    text_plain = MIMEText(text, _subtype='plain', _charset='UTF-8')
    msg.attach(text_plain)

    try:
        client = smtplib.SMTP_SSL()
        client.connect(cfg['notice_email']['stmp_domain'], cfg['notice_email']['stmp_port'])
        client.set_debuglevel(0)
        client.login(username, password)
        # 发件人和认证地址必须一致
        # 备注：若想取到DATA命令返回值,可参考smtplib的sendmaili封装方法:
        #      使用SMTP.mail/SMTP.rcpt/SMTP.data方法
        client.sendmail(username, recipients, msg.as_string())
        client.quit()
        print('邮件发送成功！')
    except smtplib.SMTPConnectError as e:
        print('邮件发送失败，连接失败:', e.smtp_code, e.smtp_error)
    except smtplib.SMTPAuthenticationError as e:
        print('邮件发送失败，认证错误:', e.smtp_code, e.smtp_error)
    except smtplib.SMTPSenderRefused as e:
        print('邮件发送失败，发件人被拒绝:', e.smtp_code, e.smtp_error)
    except smtplib.SMTPRecipientsRefused as e:
        print('邮件发送失败，收件人被拒绝:', e.smtp_code, e.smtp_error)
    except smtplib.SMTPDataError as e:
        print('邮件发送失败，数据接收拒绝:', e.smtp_code, e.smtp_error)
    except smtplib.SMTPException as e:
        print('邮件发送失败, ', e.message)
    except Exception as e:
        print('邮件发送异常, ', str(e))
