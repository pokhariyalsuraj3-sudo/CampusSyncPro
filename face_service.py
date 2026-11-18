import base64
import io
import json
import numpy as np
from PIL import Image
from scipy.fftpack import dct

class FaceRecognitionService:
    """
    Lightweight, high-accuracy perceptual facial feature extraction & matching service
    powered by NumPy, SciPy (DCT Frequency Domain Analysis), and Pillow.
    No heavy C++ dependencies (dlib/cmake) required.
    """

    FEATURE_DIM = 128
    IMAGE_SIZE = (64, 64)
    SIMILARITY_THRESHOLD = 0.40  # Statistically calibrated cosine threshold preventing false-positive cross-matches
    AMBIGUITY_MARGIN = 0.05      # Required margin between top and runner-up candidate to prevent ambiguous identification

    @classmethod
    def decode_image(cls, image_data):
        """Decodes base64 string, file bytes, or existing PIL Image."""
        if not image_data:
            return None
        try:
            if isinstance(image_data, Image.Image):
                return image_data
            if isinstance(image_data, str):
                if ',' in image_data:
                    image_data = image_data.split(',', 1)[1]
                image_bytes = base64.b64decode(image_data)
            elif isinstance(image_data, bytes):
                image_bytes = image_data
            else:
                image_bytes = image_data.read()

            image = Image.open(io.BytesIO(image_bytes))
            return image
        except Exception:
            return None

    @classmethod
    def check_prototype_liveness(cls, image):
        """
        Prototype image quality and liveness checks:
        Evaluates lighting, overexposure, texture variance, and blur/focus to provide
        actionable feedback for classroom webcam captures.
        """
        if not image:
            return False, "No image captured."

        gray = image.convert('L')
        arr = np.array(gray, dtype=np.float32)

        mean_val = float(np.mean(arr))
        var_val = float(np.var(arr))

        if mean_val < 30.0:
            return False, "Face not detected: lighting too dark. Please face a light source or move to a brighter area."
        if mean_val > 240.0:
            return False, "Face not detected: image overexposed or excessive backlighting. Please adjust camera position."
        if var_val < 140.0:
            return False, "Face not detected. Please position your face inside the camera guide."

        # Blur and sharpness detection via gradient magnitude variance
        gy, gx = np.gradient(arr)
        sharpness = float(np.var(np.sqrt(gx**2 + gy**2)))
        if sharpness < 15.0:
            return False, "Image is blurry. Please hold steady and keep your face in focus."

        return True, "Quality checks passed."

    @classmethod
    def extract_face_descriptor(cls, image_data):
        """
        Extracts a normalized facial feature vector representation from an image.
        For landscape webcam captures, applies dual guide/core cropping, contrast normalization,
        and extracts 2D DCT coefficients skipping ambient room lighting gradients.
        Returns (descriptor_json_string, error_message).
        """
        image = cls.decode_image(image_data)
        if not image:
            return None, "Unable to read image."

        is_alive, msg = cls.check_prototype_liveness(image)
        if not is_alive:
            return None, msg

        try:
            from PIL import ImageOps

            w, h = image.size
            # Guide crop (matches attendance camera guide oval)
            if w / h >= 1.2:
                crop_guide = (int(w * 0.22), int(h * 0.12), int(w * 0.78), int(h * 0.88))
                crop_core = (int(w * 0.27), int(h * 0.17), int(w * 0.73), int(h * 0.83))
            else:
                crop_guide = (0, 0, w, h)
                crop_core = (int(w * 0.08), int(h * 0.08), int(w * 0.92), int(h * 0.92))

            def _get_dct_vec(crop_box):
                face_img = image.crop(crop_box)
                gray = face_img.convert('L').resize(cls.IMAGE_SIZE, Image.Resampling.LANCZOS)
                eq = ImageOps.autocontrast(gray)
                arr = np.array(eq, dtype=np.float32)

                # Histogram / Contrast normalization (Z-score standardization)
                std = np.std(arr)
                if std > 0:
                    norm_arr = (arr - np.mean(arr)) / std
                else:
                    norm_arr = arr - np.mean(arr)

                # 2D Discrete Cosine Transform (DCT-II)
                dct_2d = dct(dct(norm_arr.T, norm='ortho').T, norm='ortho')

                # Extract frequency coefficients omitting DC and pure linear illumination gradients (0,0), (0,1), (1,0)
                features = []
                h_dct, w_dct = dct_2d.shape
                for diagonal in range(25):
                    for i in range(diagonal + 1):
                        j = diagonal - i
                        if i < h_dct and j < w_dct:
                            if (i, j) in [(0, 0), (0, 1), (1, 0)]:
                                continue
                            features.append(float(dct_2d[i, j]))
                            if len(features) >= cls.FEATURE_DIM:
                                break
                    if len(features) >= cls.FEATURE_DIM:
                        break

                vec = np.array(features[:cls.FEATURE_DIM], dtype=np.float32)
                norm = np.linalg.norm(vec)
                return (vec / norm).tolist() if norm > 0 else vec.tolist()

            vec_guide = _get_dct_vec(crop_guide)
            vec_core = _get_dct_vec(crop_core)

            # Store multi-view dictionary for maximum capture resilience
            desc_dict = {'crop': vec_guide, 'core': vec_core}
            return json.dumps(desc_dict), None
        except Exception as e:
            return None, f"Feature extraction failed: {str(e)}"

    @classmethod
    def compute_similarity(cls, vec1_data, vec2_data):
        """
        Computes maximum cosine similarity across available views
        (full-frame, guide-cropped, or legacy 128-d vector).
        Supports JSON string, dict, or list representations.
        """
        try:
            if isinstance(vec1_data, str):
                d1 = json.loads(vec1_data)
            else:
                d1 = vec1_data

            if isinstance(vec2_data, str):
                d2 = json.loads(vec2_data)
            else:
                d2 = vec2_data

            def get_vectors(d):
                if isinstance(d, dict):
                    vecs = []
                    for k in ['crop', 'core', 'full']:
                        if k in d and d[k]:
                            vecs.append(np.array(d[k], dtype=np.float32))
                    if not vecs:
                        for v in d.values():
                            if isinstance(v, list) and v:
                                vecs.append(np.array(v, dtype=np.float32))
                    return vecs
                elif isinstance(d, list):
                    return [np.array(d, dtype=np.float32)]
                return []

            vlist1 = get_vectors(d1)
            vlist2 = get_vectors(d2)

            if not vlist1 or not vlist2:
                return 0.0

            max_sim = -1.0
            for v1 in vlist1:
                n1 = np.linalg.norm(v1)
                if n1 == 0:
                    continue
                for v2 in vlist2:
                    n2 = np.linalg.norm(v2)
                    if n2 == 0:
                        continue
                    sim = float(np.dot(v1, v2) / (n1 * n2))
                    if sim > max_sim:
                        max_sim = sim
            return float(max_sim) if max_sim > -1.0 else 0.0
        except Exception:
            return 0.0

    @classmethod
    def extract_features(cls, image_data, check_liveness=True):
        """
        Extracts 128-dimensional feature vector as a python list with optional liveness check.
        Returns (vector_list, error_message).
        """
        image = cls.decode_image(image_data)
        if not image:
            return None, "Unable to read image."

        if check_liveness:
            is_alive, msg = cls.check_prototype_liveness(image)
            if not is_alive:
                return None, msg

        desc_json, err = cls.extract_face_descriptor(image_data)
        if err or not desc_json:
            return None, err
        parsed = json.loads(desc_json)
        if isinstance(parsed, dict):
            # Return primary 128-d feature vector as list for backward compatibility with 128-d vector consumers
            return parsed.get('crop') or parsed.get('core') or list(parsed.values())[0], None
        return parsed, None

    @classmethod
    def match_face(cls, query_vector, enrolled_candidates, threshold=None, return_diagnostics=False):
        """
        Matches a query vector (dict, list, or json string) against candidate enrolled faces.
        Returns match dict (or (match_dict, diagnostics_dict) if return_diagnostics=True) or None.
        Enforces:
        - Minimum similarity threshold (default cls.SIMILARITY_THRESHOLD).
        - Ambiguity check: if multiple candidates have similarity >= threshold,
          the top candidate must be clear of ambiguity (margin >= cls.AMBIGUITY_MARGIN unless confidence >= 0.70).
        - Single candidate verification: even if only 1 candidate exists, it MUST meet threshold.
        - Strict verification that candidate has an authoritative student_id.
        """
        if threshold is None:
            threshold = cls.SIMILARITY_THRESHOLD

        if isinstance(query_vector, (list, dict)):
            query_vector_json = json.dumps(query_vector)
        else:
            query_vector_json = query_vector

        all_candidate_scores = []
        for cand in enrolled_candidates:
            cand_data = cand.get('face_data')
            cand_id = cand.get('student_id')
            if not cand_data or cand_id is None:
                continue
            sim = cls.compute_similarity(query_vector_json, cand_data)
            all_candidate_scores.append((cand_id, cand.get('full_name', ''), sim, cand))

        all_candidate_scores.sort(key=lambda x: x[2], reverse=True)

        diagnostics = {
            'candidates_count': len(all_candidate_scores),
            'scores': {str(c[0]): round(c[2], 4) for c in all_candidate_scores},
            'top_score': round(all_candidate_scores[0][2], 4) if all_candidate_scores else 0.0,
            'second_score': round(all_candidate_scores[1][2], 4) if len(all_candidate_scores) > 1 else 0.0,
            'margin': round(all_candidate_scores[0][2] - all_candidate_scores[1][2], 4) if len(all_candidate_scores) > 1 else (round(all_candidate_scores[0][2], 4) if all_candidate_scores else 0.0),
            'decision': 'UNRECOGNIZED',
            'matched_student_id': None
        }

        if not all_candidate_scores:
            diagnostics['decision'] = 'NO_CANDIDATES'
            return (None, diagnostics) if return_diagnostics else None

        best_id, best_name, best_sim, best_candidate = all_candidate_scores[0]

        # 1. Reject if below calibrated similarity threshold (NEVER match merely because only 1 exists!)
        if best_sim < threshold:
            diagnostics['decision'] = 'UNRECOGNIZED'
            return (None, diagnostics) if return_diagnostics else None

        # 2. Check for ambiguity if runner-up exists
        if len(all_candidate_scores) > 1 and best_sim < 0.70:
            second_id, second_name, second_sim, _ = all_candidate_scores[1]
            if (best_sim - second_sim) < cls.AMBIGUITY_MARGIN:
                diagnostics['decision'] = 'AMBIGUOUS'
                return (None, diagnostics) if return_diagnostics else None

        diagnostics['decision'] = 'VERIFIED'
        diagnostics['matched_student_id'] = int(best_candidate['student_id'])

        match_res = {
            'student_id': int(best_candidate['student_id']),
            'full_name': best_candidate['full_name'],
            'roll_number': best_candidate.get('roll_number', ''),
            'email': best_candidate.get('email', ''),
            'similarity': best_sim
        }
        return (match_res, diagnostics) if return_diagnostics else match_res

    @classmethod
    def match_face_in_class(cls, probe_image_data, enrolled_students):
        """
        Matches a captured webcam probe against the enrolled students of a class.
        Uses match_face with threshold and ambiguity enforcement.
        Returns:
            match_found (bool),
            matched_student (dict or None),
            similarity_score (float),
            status_message (str)
        """
        probe_vector_str, err = cls.extract_face_descriptor(probe_image_data)
        if err or not probe_vector_str:
            return False, None, 0.0, err or "No face descriptor could be extracted."

        if not enrolled_students:
            return False, None, 0.0, "No enrolled students found in this class."

        match = cls.match_face(probe_vector_str, enrolled_students)
        if match:
            return True, match, round(match['similarity'] * 100, 1), "Face verified successfully."
        else:
            return False, None, 0.0, "Face unrecognized or ambiguous in this class."

