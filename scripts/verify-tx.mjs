import {AuthInfo, SignDoc, TxRaw} from 'cosmjs-types/cosmos/tx/v1beta1/tx.js';
import {PubKey} from 'cosmjs-types/cosmos/crypto/secp256k1/keys.js';
import {Secp256k1, Secp256k1Signature, sha256, ripemd160} from '@cosmjs/crypto';
import {toBech32} from '@cosmjs/encoding';

// Verify the exact CLI-produced bytes using an independent crypto library.
// No network or key access. Account numbers never pass through JS Number.
try {
    const chunks = [];
    let size = 0;
    for await (const chunk of process.stdin) {
        size += chunk.length;
        if (size > 2 * 1024 * 1024) throw new Error('input limit');
        chunks.push(chunk);
    }
    const input = JSON.parse(Buffer.concat(chunks).toString('utf8'));
    if (typeof input.account_number !== 'string' || !/^(0|[1-9][0-9]*)$/.test(input.account_number)
        || BigInt(input.account_number) > 18446744073709551615n) throw new Error('account number');
    const raw = TxRaw.decode(Buffer.from(input.tx_bytes, 'base64'));
    const auth = AuthInfo.decode(raw.authInfoBytes);
    if (raw.signatures.length !== 1 || raw.signatures[0].length !== 64 || auth.signerInfos.length !== 1) throw new Error('signers');
    const signer = auth.signerInfos[0];
    if (signer.publicKey?.typeUrl !== '/cosmos.crypto.secp256k1.PubKey' || signer.modeInfo?.single?.mode !== 1) throw new Error('mode');
    const pubkey = PubKey.decode(signer.publicKey.value).key;
    if (pubkey.length !== 33 || toBech32('structs', ripemd160(sha256(pubkey))) !== input.address) throw new Error('address');
    const signBytes = SignDoc.encode({bodyBytes: raw.bodyBytes, authInfoBytes: raw.authInfoBytes,
        chainId: input.chain_id, accountNumber: BigInt(input.account_number)}).finish();
    if (!await Secp256k1.verifySignature(Secp256k1Signature.fromFixedLength(raw.signatures[0]), sha256(signBytes), pubkey)) throw new Error('signature');
    console.log(JSON.stringify({valid: true, sequence: signer.sequence.toString(), address: input.address}));
} catch {
    console.error('Signed transaction verification failed');
    process.exitCode = 1;
}
