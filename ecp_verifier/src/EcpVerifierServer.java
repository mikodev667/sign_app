import com.sun.net.httpserver.HttpExchange;
import com.sun.net.httpserver.HttpServer;

import kz.gov.pki.kalkan.jce.provider.KalkanProvider;
import kz.gov.pki.kalkan.jce.provider.cms.CMSSignedData;
import kz.gov.pki.kalkan.jce.provider.cms.CMSProcessable;
import kz.gov.pki.kalkan.jce.provider.cms.SignerInformation;
import kz.gov.pki.kalkan.jce.provider.cms.SignerInformationStore;

import java.io.ByteArrayOutputStream;
import java.io.IOException;
import java.io.OutputStream;
import java.net.InetSocketAddress;
import java.nio.charset.StandardCharsets;
import java.security.Provider;
import java.security.Security;
import java.security.cert.CertStore;
import java.security.cert.X509Certificate;
import java.util.Base64;
import java.util.Collection;
import java.util.Date;
import java.util.Iterator;

import kz.gov.pki.kalkan.asn1.DEROctetString;
import kz.gov.pki.kalkan.asn1.ocsp.OCSPObjectIdentifiers;
import kz.gov.pki.kalkan.asn1.x509.X509Extension;
import kz.gov.pki.kalkan.asn1.x509.X509Extensions;
import kz.gov.pki.kalkan.ocsp.BasicOCSPResp;
import kz.gov.pki.kalkan.ocsp.CertificateID;
import kz.gov.pki.kalkan.ocsp.OCSPReq;
import kz.gov.pki.kalkan.ocsp.OCSPReqGenerator;
import kz.gov.pki.kalkan.ocsp.OCSPResp;
import kz.gov.pki.kalkan.ocsp.RevokedStatus;
import kz.gov.pki.kalkan.ocsp.SingleResp;
import kz.gov.pki.kalkan.ocsp.UnknownStatus;

import javax.security.auth.x500.X500Principal;
import java.io.FileInputStream;
import java.math.BigInteger;
import java.net.HttpURLConnection;
import java.net.URL;
import java.security.SecureRandom;
import java.security.cert.CertificateFactory;
import java.security.cert.CertPath;
import java.security.cert.CertPathValidator;
import java.security.cert.PKIXParameters;
import java.security.cert.TrustAnchor;
import java.util.ArrayList;
import java.util.HashSet;
import java.util.Hashtable;
import java.util.List;
import java.util.Set;

import kz.gov.pki.kalkan.asn1.cms.Attribute;
import kz.gov.pki.kalkan.asn1.cms.AttributeTable;
import kz.gov.pki.kalkan.asn1.cms.ContentInfo;
import kz.gov.pki.kalkan.asn1.pkcs.PKCSObjectIdentifiers;
import kz.gov.pki.kalkan.asn1.knca.KNCAObjectIdentifiers;
import kz.gov.pki.kalkan.tsp.TimeStampToken;
import kz.gov.pki.kalkan.tsp.TimeStampTokenInfo;
import kz.gov.pki.kalkan.tsp.TSPAlgorithms;

import java.security.MessageDigest;
import java.security.cert.X509CertSelector;
import java.util.Arrays;


public class EcpVerifierServer {

    private static final String TRUSTED_CERTS_DIR = "ecp_verifier/certs/production2022/production";
    private static final String OCSP_URL = "http://ocsp.pki.gov.kz";

    public static void main(String[] args) throws Exception {
        addKalkanProvider();

        HttpServer server = HttpServer.create(new InetSocketAddress("127.0.0.1", 9001), 0);

        server.createContext("/health", exchange -> {
            sendJson(exchange, 200, "{\"ok\":true,\"service\":\"ecp-verifier\"}");
        });

        server.createContext("/verify-ecp", exchange -> {
            if (!"POST".equalsIgnoreCase(exchange.getRequestMethod())) {
                sendJson(exchange, 405, "{\"ok\":false,\"error\":\"Only POST is allowed\"}");
                return;
            }

            try {
                String requestBody = new String(exchange.getRequestBody().readAllBytes(), StandardCharsets.UTF_8);

                String cms = extractJsonString(requestBody, "cms");
                String expectedDocumentHash = extractJsonString(requestBody, "expected_document_hash");
                String expectedIin = extractJsonString(requestBody, "expected_iin");

                if (cms.isBlank()) {
                    sendJson(exchange, 400, "{\"ok\":false,\"error\":\"cms is required\"}");
                    return;
                }

                if (expectedDocumentHash.isBlank()) {
                    sendJson(exchange, 400, "{\"ok\":false,\"error\":\"expected_document_hash is required\"}");
                    return;
                }

                if (expectedIin.isBlank()) {
                    sendJson(exchange, 400, "{\"ok\":false,\"error\":\"expected_iin is required\"}");
                    return;
                }

                String result = verifyCms(cms, expectedDocumentHash, expectedIin);
                sendJson(exchange, 200, result);

            } catch (Exception e) {
                String errorJson = "{"
                        + "\"ok\":false,"
                        + "\"error\":\"" + escape(e.getClass().getSimpleName() + ": " + e.getMessage()) + "\""
                        + "}";

                sendJson(exchange, 500, errorJson);
            }
        });

        server.start();

        System.out.println("ECP verifier service started:");
        System.out.println("Health: http://127.0.0.1:9001/health");
        System.out.println("Verify: POST http://127.0.0.1:9001/verify-ecp");
    }

    private static String verifyCms(String cmsText, String expectedDocumentHash, String expectedIin) throws Exception {
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

        List<X509Certificate> trustedCertificates = loadTrustedCertificates();
        boolean chainValid = validateCertificateChain(certificate, cmsSignedData, trustedCertificates);

        boolean certificateTypeValid = isCertificateAllowedForSigning(certificate);

        String ocspStatus = "not_checked";
        boolean ocspGood = false;

        try {
            X509Certificate issuerCertificate = findIssuerCertificate(certificate, cmsSignedData, trustedCertificates);

            if (issuerCertificate != null) {
                ocspStatus = checkOcspStatus(certificate, issuerCertificate);
                ocspGood = "good".equals(ocspStatus);
            } else {
                ocspStatus = "issuer_not_found";
            }
        } catch (Exception e) {
            ocspStatus = "error: " + e.getClass().getSimpleName() + ": " + e.getMessage();
        }

        boolean timestampValid = false;
        String timestampStatus = "not_implemented_yet";

        boolean ok =
                cmsValid &&
                documentHashMatches &&
                iinMatches &&
                certificateDateValid &&
                chainValid &&
                certificateTypeValid &&
                ocspGood;

        return "{"
                + "\"ok\":" + ok + ","
                + "\"cms_valid\":" + cmsValid + ","
                + "\"document_hash_matches\":" + documentHashMatches + ","
                + "\"iin_matches\":" + iinMatches + ","
                + "\"certificate_date_valid\":" + certificateDateValid + ","
                + "\"chain_valid\":" + chainValid + ","
                + "\"certificate_type_valid\":" + certificateTypeValid + ","
                + "\"ocsp_good\":" + ocspGood + ","
                + "\"ocsp_status\":\"" + escape(ocspStatus) + "\","
                + "\"timestamp_valid\":" + timestampValid + ","
                + "\"timestamp_status\":\"" + escape(timestampStatus) + "\","
                + "\"certificate_subject\":\"" + escape(subject) + "\","
                + "\"certificate_iin\":\"" + escape(certificateIin) + "\","
                + "\"certificate_serial\":\"" + escape(serial) + "\","
                + "\"certificate_not_before\":\"" + escape(certificate.getNotBefore().toString()) + "\","
                + "\"certificate_not_after\":\"" + escape(certificate.getNotAfter().toString()) + "\","
                + "\"signed_payload\":\"" + escape(signedPayload) + "\","
                + "\"error\":\"\""
                + "}";
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

        int offset = 0;

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

    private static String extractJsonString(String json, String key) {
        String pattern = "\"" + key + "\"\\s*:\\s*\"";
        java.util.regex.Pattern compiledPattern = java.util.regex.Pattern.compile(pattern);
        java.util.regex.Matcher matcher = compiledPattern.matcher(json);

        if (!matcher.find()) {
            return "";
        }

        int start = matcher.end();
        StringBuilder value = new StringBuilder();
        boolean escaped = false;

        for (int i = start; i < json.length(); i++) {
            char current = json.charAt(i);

            if (escaped) {
                switch (current) {
                    case 'n':
                        value.append('\n');
                        break;
                    case 'r':
                        value.append('\r');
                        break;
                    case 't':
                        value.append('\t');
                        break;
                    case '"':
                        value.append('"');
                        break;
                    case '\\':
                        value.append('\\');
                        break;
                    default:
                        value.append(current);
                        break;
                }

                escaped = false;
                continue;
            }

            if (current == '\\') {
                escaped = true;
                continue;
            }

            if (current == '"') {
                break;
            }

            value.append(current);
        }

        return value.toString();
    }

    private static void sendJson(HttpExchange exchange, int statusCode, String json) throws IOException {
        byte[] responseBytes = json.getBytes(StandardCharsets.UTF_8);

        exchange.getResponseHeaders().set("Content-Type", "application/json; charset=utf-8");
        exchange.sendResponseHeaders(statusCode, responseBytes.length);

        try (OutputStream outputStream = exchange.getResponseBody()) {
            outputStream.write(responseBytes);
        }
    }

    private static List<X509Certificate> loadTrustedCertificates() throws Exception {
        List<X509Certificate> certificates = new ArrayList<>();

        java.io.File directory = new java.io.File(TRUSTED_CERTS_DIR);

        if (!directory.exists() || !directory.isDirectory()) {
            throw new Exception("Trusted certificates directory not found: " + TRUSTED_CERTS_DIR);
        }

        java.io.File[] files = directory.listFiles();

        if (files == null) {
            return certificates;
        }

        CertificateFactory certificateFactory = CertificateFactory.getInstance(
                "X.509",
                KalkanProvider.PROVIDER_NAME
        );

        for (java.io.File file : files) {
            String name = file.getName().toLowerCase();

            if (
                    name.endsWith(".cer") ||
                    name.endsWith(".crt") ||
                    name.endsWith(".pem")
            ) {
                try (FileInputStream inputStream = new FileInputStream(file)) {
                    X509Certificate certificate = (X509Certificate) certificateFactory.generateCertificate(inputStream);
                    certificates.add(certificate);
                }
            }
        }

        if (certificates.isEmpty()) {
            throw new Exception("No trusted certificates found in: " + TRUSTED_CERTS_DIR);
        }

        return certificates;
    }

    private static boolean validateCertificateChain(
        X509Certificate signerCertificate,
        CMSSignedData cmsSignedData,
        List<X509Certificate> trustedCertificates
    ) {
        try {
            Date now = new Date();

            X509Certificate current = signerCertificate;

            for (int depth = 0; depth < 10; depth++) {
                if (now.before(current.getNotBefore()) || now.after(current.getNotAfter())) {
                    System.err.println("Certificate in chain is expired or not yet valid: "
                            + current.getSubjectX500Principal().getName());
                    return false;
                }

                X509Certificate issuer = findIssuerCertificate(
                        current,
                        cmsSignedData,
                        trustedCertificates
                );

                if (issuer == null) {
                    System.err.println("Issuer not found for: "
                            + current.getSubjectX500Principal().getName());
                    return false;
                }

                try {
                    current.verify(
                            issuer.getPublicKey(),
                            KalkanProvider.PROVIDER_NAME
                    );
                } catch (Exception e) {
                    System.err.println("Certificate signature verification failed: " + e.getMessage());
                    return false;
                }

                if (isTrustedCertificate(issuer, trustedCertificates)) {
                    if (now.before(issuer.getNotBefore()) || now.after(issuer.getNotAfter())) {
                        System.err.println("Trusted issuer is expired or not yet valid: "
                                + issuer.getSubjectX500Principal().getName());
                        return false;
                    }

                    return true;
                }

                if (isSameCertificate(current, issuer)) {
                    return isTrustedCertificate(issuer, trustedCertificates);
                }

                current = issuer;
            }

            System.err.println("Certificate chain depth exceeded.");
            return false;

        } catch (Exception e) {
            System.err.println("Certificate chain validation error: " + e.getMessage());
            return false;
        }
    }

    private static List<X509Certificate> buildCertificateChain(
            X509Certificate signerCertificate,
            CMSSignedData cmsSignedData,
            List<X509Certificate> trustedCertificates
    ) throws Exception {
        List<X509Certificate> chain = new ArrayList<>();
        chain.add(signerCertificate);

        X509Certificate current = signerCertificate;

        for (int depth = 0; depth < 5; depth++) {
            X509Certificate issuer = findIssuerCertificate(
                    current,
                    cmsSignedData,
                    trustedCertificates
            );

            if (issuer == null) {
                break;
            }

            if (isSameCertificate(current, issuer)) {
                break;
            }

            if (isTrustedCertificate(issuer, trustedCertificates)) {
                chain.add(issuer);
                break;
            }

            chain.add(issuer);
            current = issuer;
        }

        return chain;
    }

    private static X509Certificate findIssuerCertificate(
            X509Certificate certificate,
            CMSSignedData cmsSignedData,
            List<X509Certificate> trustedCertificates
    ) throws Exception {
        X500Principal issuer = certificate.getIssuerX500Principal();

        List<X509Certificate> candidates = new ArrayList<>();

        CertStore certStore = cmsSignedData.getCertificatesAndCRLs(
                "Collection",
                KalkanProvider.PROVIDER_NAME
        );

        Collection<?> cmsCertificates = certStore.getCertificates(null);

        for (Object item : cmsCertificates) {
            if (item instanceof X509Certificate) {
                candidates.add((X509Certificate) item);
            }
        }

        candidates.addAll(trustedCertificates);

        for (X509Certificate candidate : candidates) {
            if (issuer.equals(candidate.getSubjectX500Principal())) {
                try {
                    certificate.verify(
                            candidate.getPublicKey(),
                            KalkanProvider.PROVIDER_NAME
                    );
                    return candidate;
                } catch (Exception ignored) {
                }
            }
        }

        return null;
    }

    private static boolean isTrustedCertificate(
            X509Certificate certificate,
            List<X509Certificate> trustedCertificates
    ) {
        for (X509Certificate trustedCertificate : trustedCertificates) {
            if (isSameCertificate(certificate, trustedCertificate)) {
                return true;
            }
        }

        return false;
    }

    private static boolean isSameCertificate(
            X509Certificate first,
            X509Certificate second
    ) {
        if (first == null || second == null) {
            return false;
        }

        return first.getSerialNumber().equals(second.getSerialNumber())
                && first.getIssuerX500Principal().equals(second.getIssuerX500Principal());
    }

    private static boolean isCertificateAllowedForSigning(X509Certificate certificate) {
        boolean[] keyUsage = certificate.getKeyUsage();

        if (keyUsage == null) {
            return true;
        }

        boolean digitalSignature = keyUsage.length > 0 && keyUsage[0];
        boolean nonRepudiation = keyUsage.length > 1 && keyUsage[1];

        return digitalSignature || nonRepudiation;
    }

    private static String checkOcspStatus(
            X509Certificate certificate,
            X509Certificate issuerCertificate
    ) throws Exception {
        byte[] ocspRequestBytes = buildOcspRequest(
                certificate.getSerialNumber(),
                issuerCertificate
        );

        URL url = new URL(OCSP_URL);
        HttpURLConnection connection = (HttpURLConnection) url.openConnection();

        connection.setDoOutput(true);
        connection.setRequestMethod("POST");
        connection.setRequestProperty("Content-Type", "application/ocsp-request");
        connection.setConnectTimeout(10000);
        connection.setReadTimeout(15000);

        try (OutputStream outputStream = connection.getOutputStream()) {
            outputStream.write(ocspRequestBytes);
        }

        try {
            OCSPResp response = new OCSPResp(connection.getInputStream());

            if (response.getStatus() != 0) {
                return "ocsp_response_status_" + response.getStatus();
            }

            BasicOCSPResp basicResponse = (BasicOCSPResp) response.getResponseObject();

            X509Certificate ocspCertificate = basicResponse.getCerts(KalkanProvider.PROVIDER_NAME)[0];

            boolean ocspSignatureValid = basicResponse.verify(
                    ocspCertificate.getPublicKey(),
                    KalkanProvider.PROVIDER_NAME
            );

            if (!ocspSignatureValid) {
                return "ocsp_signature_invalid";
            }

            SingleResp[] responses = basicResponse.getResponses();

            if (responses == null || responses.length == 0) {
                return "no_ocsp_single_response";
            }

            Object status = responses[0].getCertStatus();

            if (status == null) {
                return "good";
            }

            if (status instanceof RevokedStatus) {
                return "revoked";
            }

            if (status instanceof UnknownStatus) {
                return "unknown";
            }

            return "unknown_status_type";

        } finally {
            connection.disconnect();
        }
    }

    private static byte[] buildOcspRequest(
            BigInteger serialNumber,
            X509Certificate issuerCertificate
    ) throws Exception {
        OCSPReqGenerator generator = new OCSPReqGenerator();

        CertificateID certificateId = new CertificateID(
                CertificateID.HASH_SHA1,
                issuerCertificate,
                serialNumber,
                KalkanProvider.PROVIDER_NAME
        );

        generator.addRequest(certificateId);
        generator.setRequestExtensions(generateOcspExtensions());

        OCSPReq request = generator.generate();

        return request.getEncoded();
    }

    private static X509Extensions generateOcspExtensions() {
        SecureRandom secureRandom = new SecureRandom();

        byte[] nonce = new byte[8];
        secureRandom.nextBytes(nonce);

        Hashtable extensions = new Hashtable();

        X509Extension nonceExtension = new X509Extension(
                false,
                new DEROctetString(new DEROctetString(nonce))
        );

        extensions.put(
                OCSPObjectIdentifiers.id_pkix_ocsp_nonce,
                nonceExtension
        );

        return new X509Extensions(extensions);
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

