import kz.gov.pki.kalkan.jce.provider.KalkanProvider;
import kz.gov.pki.kalkan.jce.provider.cms.CMSSignedData;
import kz.gov.pki.kalkan.jce.provider.cms.CMSProcessable;
import kz.gov.pki.kalkan.jce.provider.cms.SignerInformation;
import kz.gov.pki.kalkan.jce.provider.cms.SignerInformationStore;

import java.io.ByteArrayOutputStream;
import java.nio.charset.StandardCharsets;
import java.nio.file.Files;
import java.nio.file.Path;
import java.security.Provider;
import java.security.Security;
import java.security.cert.CertStore;
import java.security.cert.X509Certificate;
import java.util.Base64;
import java.util.Collection;
import java.util.Date;
import java.util.Iterator;

public class EcpCmsVerifier {
    public static void main(String[] args) {
        if (args.length < 3) {
            printJson(false, "Usage: java EcpCmsVerifier <cms_file> <expected_document_hash> <expected_iin>", "", "", "", "", false, false, false, false);
            System.exit(1);
        }

        String cmsFilePath = args[0];
        String expectedDocumentHash = args[1];
        String expectedIin = args[2];

        try {
            addKalkanProvider();

            String cmsText = Files.readString(Path.of(cmsFilePath), StandardCharsets.UTF_8);
            byte[] cmsBytes = readPemCms(cmsText);

            CMSSignedData cmsSignedData = new CMSSignedData(cmsBytes);

            String signedPayload = extractSignedPayload(cmsSignedData);

            boolean documentHashMatches = signedPayload.contains("\"document_hash\": \"" + expectedDocumentHash + "\"")
                    || signedPayload.contains("\"document_hash\":\"" + expectedDocumentHash + "\"");

            SignerInformation signerInfo = getFirstSigner(cmsSignedData);
            X509Certificate certificate = getSignerCertificate(cmsSignedData, signerInfo);

            boolean cmsValid = signerInfo.verify(certificate, KalkanProvider.PROVIDER_NAME);

            String subject = certificate.getSubjectX500Principal().getName();
            String certificateIin = extractIin(subject);
            String serial = certificate.getSerialNumber().toString();

            boolean iinMatches = expectedIin.equals(certificateIin);

            Date now = new Date();
            boolean certificateDateValid = now.after(certificate.getNotBefore()) && now.before(certificate.getNotAfter());

            boolean ok = cmsValid && documentHashMatches && iinMatches && certificateDateValid;

            printJson(
                    ok,
                    "",
                    subject,
                    certificateIin,
                    serial,
                    signedPayload,
                    cmsValid,
                    documentHashMatches,
                    iinMatches,
                    certificateDateValid
            );

            if (!ok) {
                System.exit(2);
            }

        } catch (Exception e) {
            printJson(false, escape(e.getClass().getSimpleName() + ": " + e.getMessage()), "", "", "", "", false, false, false, false);
            System.exit(3);
        }
    }

    private static void addKalkanProvider() {
        Provider provider = new KalkanProvider();

        if (Security.getProvider(provider.getName()) == null) {
            Security.addProvider(provider);
        }
    }

    private static byte[] readPemCms(String cmsText) {
        String cleaned = cmsText
                .replace("-----BEGIN CMS-----", "")
                .replace("-----END CMS-----", "")
                .replaceAll("\\s+", "");

        return Base64.getDecoder().decode(cleaned);
    }

    private static String extractSignedPayload(CMSSignedData cmsSignedData) throws Exception {
        CMSProcessable signedContent = cmsSignedData.getSignedContent();

        if (signedContent == null) {
            return "";
        }

        Object content = signedContent.getContent();

        if (content instanceof byte[]) {
            return new String((byte[]) content, StandardCharsets.UTF_8);
        }

        ByteArrayOutputStream outputStream = new ByteArrayOutputStream();
        signedContent.write(outputStream);

        return outputStream.toString(StandardCharsets.UTF_8);
    }

    private static SignerInformation getFirstSigner(CMSSignedData cmsSignedData) throws Exception {
        SignerInformationStore signerStore = cmsSignedData.getSignerInfos();
        Collection<?> signers = signerStore.getSigners();

        if (signers.isEmpty()) {
            throw new Exception("No signers found in CMS.");
        }

        Iterator<?> iterator = signers.iterator();
        return (SignerInformation) iterator.next();
    }

    private static X509Certificate getSignerCertificate(CMSSignedData cmsSignedData, SignerInformation signerInfo) throws Exception {
        CertStore certStore = cmsSignedData.getCertificatesAndCRLs(
                "Collection",
                KalkanProvider.PROVIDER_NAME
        );

        Collection<?> certificates = certStore.getCertificates(signerInfo.getSID());

        if (certificates.isEmpty()) {
            throw new Exception("Signer certificate not found in CMS.");
        }

        Iterator<?> iterator = certificates.iterator();
        return (X509Certificate) iterator.next();
    }

    private static String extractIin(String subject) {
        if (subject == null) {
            return "";
        }

        /*
            Example from real certificate subject:

            2.5.4.5=#130f49494e303530333035353031353433

            Hex value decodes to:
            IIN050305501543
        */
        java.util.regex.Matcher hexSerialMatcher = java.util.regex.Pattern
                .compile("2\\.5\\.4\\.5=#([0-9A-Fa-f]+)")
                .matcher(subject);

        if (hexSerialMatcher.find()) {
            String hexValue = hexSerialMatcher.group(1);
            String decoded = decodeAsn1HexString(hexValue);

            java.util.regex.Matcher iinMatcher = java.util.regex.Pattern
                    .compile("IIN(\\d{12})")
                    .matcher(decoded);

            if (iinMatcher.find()) {
                return iinMatcher.group(1);
            }

            java.util.regex.Matcher digitsMatcher = java.util.regex.Pattern
                    .compile("\\b\\d{12}\\b")
                    .matcher(decoded);

            if (digitsMatcher.find()) {
                return digitsMatcher.group(0);
            }
        }

        String marker = "SERIALNUMBER=IIN";
        int index = subject.indexOf(marker);

        if (index >= 0) {
            int start = index + marker.length();
            int end = Math.min(start + 12, subject.length());

            String value = subject.substring(start, end);

            if (value.matches("\\d{12}")) {
                return value;
            }
        }

        java.util.regex.Matcher iinTextMatcher = java.util.regex.Pattern
                .compile("IIN(\\d{12})")
                .matcher(subject);

        if (iinTextMatcher.find()) {
            return iinTextMatcher.group(1);
        }

        java.util.regex.Matcher matcher = java.util.regex.Pattern
                .compile("\\b\\d{12}\\b")
                .matcher(subject);

        if (matcher.find()) {
            return matcher.group(0);
        }

        return "";
    }

    private static String decodeAsn1HexString(String hex) {
        if (hex == null || hex.length() < 2) {
            return "";
        }

        byte[] bytes = hexToBytes(hex);

        if (bytes.length < 2) {
            return "";
        }

        /*
            ASN.1 string format:
            first byte  = tag
            second byte = length
            remaining   = string bytes

            Example:
            13 0f 49 49 4e 30 35...
            13 = PrintableString
            0f = length 15
            value = IIN050305501543
        */
        int offset = 0;

        int tag = bytes[offset] & 0xFF;
        offset++;

        if (offset >= bytes.length) {
            return "";
        }

        int length = bytes[offset] & 0xFF;
        offset++;

        if ((length & 0x80) != 0) {
            int lengthBytesCount = length & 0x7F;
            length = 0;

            for (int i = 0; i < lengthBytesCount && offset < bytes.length; i++) {
                length = (length << 8) | (bytes[offset] & 0xFF);
                offset++;
            }
        }

        if (offset + length > bytes.length) {
            length = bytes.length - offset;
        }

        if (length <= 0) {
            return "";
        }

        byte[] valueBytes = new byte[length];
        System.arraycopy(bytes, offset, valueBytes, 0, length);

        return new String(valueBytes, StandardCharsets.UTF_8);
    }

    private static byte[] hexToBytes(String hex) {
        String cleanHex = hex.replaceAll("\\s+", "");

        if (cleanHex.length() % 2 != 0) {
            cleanHex = "0" + cleanHex;
        }

        byte[] bytes = new byte[cleanHex.length() / 2];

        for (int i = 0; i < cleanHex.length(); i += 2) {
            bytes[i / 2] = (byte) Integer.parseInt(cleanHex.substring(i, i + 2), 16);
        }

        return bytes;
    }

    private static void printJson(
            boolean ok,
            String error,
            String certificateSubject,
            String certificateIin,
            String certificateSerial,
            String signedPayload,
            boolean cmsValid,
            boolean documentHashMatches,
            boolean iinMatches,
            boolean certificateDateValid
    ) {
        String json = "{"
                + "\"ok\":" + ok + ","
                + "\"cms_valid\":" + cmsValid + ","
                + "\"document_hash_matches\":" + documentHashMatches + ","
                + "\"iin_matches\":" + iinMatches + ","
                + "\"certificate_date_valid\":" + certificateDateValid + ","
                + "\"certificate_subject\":\"" + escape(certificateSubject) + "\","
                + "\"certificate_iin\":\"" + escape(certificateIin) + "\","
                + "\"certificate_serial\":\"" + escape(certificateSerial) + "\","
                + "\"signed_payload\":\"" + escape(signedPayload) + "\","
                + "\"error\":\"" + escape(error) + "\""
                + "}";

        System.out.println(json);
    }

    private static String escape(String value) {
        if (value == null) {
            return "";
        }

        return value
                .replace("\\", "\\\\")
                .replace("\"", "\\\"")
                .replace("\r", "\\r")
                .replace("\n", "\\n");
    }
}