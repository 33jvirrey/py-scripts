import com.sap.gateway.ip.core.customdev.util.Message;
import java.util.HashMap;

Message processData(Message message) {

    def headers = message.getHeaders()
    def body = message.getBody(String)

    def httpCode = headers["CamelHttpResponseCode"] ?: "N/A"
    def exception = headers["CamelExceptionCaught"] ?: "N/A"
    def requestUrl = headers["CamelHttpUri"] ?: headers["CamelHttpUrl"] ?: "N/A"
    def method = headers["CamelHttpMethod"] ?: "N/A"

    def logText = """
=====================
🔥 HUBSPOT ERROR LOG
=====================

📌 Timestamp:
${new Date()}

📌 CPI Message ID:
${headers["SAP_MID"]}

📌 HTTP Method:
${method}

📌 URL:
${requestUrl}

📌 HTTP Code:
${httpCode}

📌 HubSpot Response:
${body}

📌 CPI Exception:
${exception}

=====================
""".stripIndent()

    def messageLog = messageLogFactory.getMessageLog(message)
    if (messageLog != null) {
        messageLog.addAttachmentAsString("HubSpot_Error_Log.txt", logText, "text/plain")
    }

    return message
}
